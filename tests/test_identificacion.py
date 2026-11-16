"""Validación de cédula y RUC. Números fabricados con un generador independiente del código de la app."""
import pytest
from sqlalchemy import select

import ayudas
from app import identificacion, servicios, validaciones
from app.modelos import TipoId
from test_web import _crear_proveedor, equipo  # noqa: F401  (equipo es un fixture)
from ayudas import formulario_proveedor, publicar

# Valores de ejemplo de la documentación pública de python-stdnum.
CEDULA_REFERENCIA = "1714307103"
RUC_REFERENCIA = "1792060346001"


def _cedula(base9: str) -> str:
    """Completa 9 dígitos con su verificador (módulo 10), calculado aquí con otro método."""
    suma = 0
    for i, c in enumerate(base9):
        p = int(c) * (2 if i % 2 == 0 else 1)
        suma += p // 10 + p % 10  # sumar los dígitos del producto
    return base9 + str((10 - suma % 10) % 10)


def _con_verificador(prefijo: str, coeficientes) -> str:
    """Agrega el dígito verificador (módulo 11, peso final 1). Prueba prefijos hasta que el dígito sea <= 9."""
    suma = sum(int(c) * k for c, k in zip(prefijo, coeficientes))
    digito = (-suma) % 11
    assert digito <= 9, "prefijo sin verificador posible; pruebe otro"
    return prefijo + str(digito)


def ruc_privada(prefijo9="179206034", sufijo="001"):
    return _con_verificador(prefijo9, (4, 3, 2, 7, 6, 5, 4, 3, 2)) + sufijo


def ruc_publica(prefijo8="17600000", sufijo="0001"):  # tercer dígito 6 = entidad pública
    return _con_verificador(prefijo8, (3, 2, 7, 6, 5, 4, 3, 2)) + sufijo


def test_los_ejemplos_publicos_de_referencia_son_validos():
    assert identificacion.revisar("C", CEDULA_REFERENCIA).errores == []
    assert identificacion.revisar("R", RUC_REFERENCIA) == identificacion.Revision()


def test_el_generador_coincide_con_la_referencia():
    assert _cedula(CEDULA_REFERENCIA[:9]) == CEDULA_REFERENCIA
    assert ruc_privada() == RUC_REFERENCIA


# ---------------------------------------------------------------- cédula


def test_cedula_valida_y_con_cualquier_digito_cambiado():
    valida = _cedula("171430710")
    assert identificacion.revisar_cedula(valida).errores == []
    for i in range(10):
        distinta = valida[:i] + str((int(valida[i]) + 1) % 10) + valida[i + 1 :]
        assert identificacion.revisar_cedula(distinta).errores, f"no detectó el cambio en la posición {i + 1}"


@pytest.mark.parametrize("numero", ["0912345675", "0100000009", "3000000000"[:9] + "0"])
def test_cedulas_con_provincia_permitida(numero):
    numero = _cedula(numero[:9])
    assert identificacion.revisar_cedula(numero).errores == []


@pytest.mark.parametrize("provincia", ["00", "25", "31", "99"])
def test_provincia_invalida(provincia):
    r = identificacion.revisar_cedula(_cedula(provincia + "1430710"))
    assert any("provincia" in e for e in r.errores)


def test_tercer_digito_mayor_que_6():
    r = identificacion.revisar_cedula(_cedula("171" + "430710"[:0] + "430710"[:6]))
    assert r.errores == []  # tercer dígito 1: bien
    r = identificacion.revisar_cedula(_cedula("177430710"))
    assert any("tercer dígito" in e for e in r.errores)


@pytest.mark.parametrize("numero", ["", "171430710", "17143071033", "17143071A3"])
def test_cedula_de_largo_o_formato_incorrecto(numero):
    assert identificacion.revisar_cedula(numero).errores == ["Una cédula debe tener 10 dígitos."]


# ---------------------------------------------------------------- RUC de persona natural (se bloquea)


def test_ruc_natural_es_la_cedula_mas_establecimiento():
    assert identificacion.revisar_ruc(_cedula("171430710") + "001") == identificacion.Revision()
    assert identificacion.revisar_ruc(_cedula("171430710") + "012") == identificacion.Revision()


def test_ruc_natural_con_cedula_mala_o_establecimiento_cero_es_error():
    buena = _cedula("171430710")
    mala = buena[:9] + str((int(buena[9]) + 1) % 10)
    r = identificacion.revisar_ruc(mala + "001")
    assert r.errores and "cédula válida" in r.errores[0] and not r.avisos
    assert any("000" in e for e in identificacion.revisar_ruc(buena + "000").errores)


# ---------------------------------------------------------------- RUC de sociedades (solo avisa)


def test_ruc_de_sociedad_privada():
    assert identificacion.revisar_ruc(ruc_privada()) == identificacion.Revision()
    malo = ruc_privada()[:9] + str((int(ruc_privada()[9]) + 1) % 10) + "001"
    r = identificacion.revisar_ruc(malo)
    assert r.errores == [] and len(r.avisos) == 1 and "módulo 11" in r.avisos[0] and "SRI" in r.avisos[0]
    assert any("000" in a for a in identificacion.revisar_ruc(ruc_privada(sufijo="000")).avisos)


def test_ruc_de_entidad_publica():
    assert identificacion.revisar_ruc(ruc_publica()) == identificacion.Revision()
    malo = ruc_publica()[:8] + str((int(ruc_publica()[8]) + 1) % 10) + "0001"
    r = identificacion.revisar_ruc(malo)
    assert r.errores == [] and "entidad pública" in r.avisos[0]
    assert any("0000" in a for a in identificacion.revisar_ruc(ruc_publica(sufijo="0000")).avisos)


@pytest.mark.parametrize("tercero", ["7", "8"])
def test_ruc_con_tercer_digito_desconocido_solo_avisa(tercero):
    r = identificacion.revisar_ruc("17" + tercero + "0000000001")
    assert r.errores == [] and "tercer dígito" in r.avisos[0]


def test_ruc_de_largo_incorrecto_y_otros_tipos():
    assert identificacion.revisar_ruc("179206034600").errores == ["Un RUC debe tener 13 dígitos."]
    assert identificacion.revisar("P", "AB123") == identificacion.Revision()  # pasaporte: no se revisa
    assert identificacion.revisar(None, "123") == identificacion.Revision()


# ---------------------------------------------------------------- integración en la app


def _ids(sesion):
    return {t.codigo: t.id for t in sesion.scalars(select(TipoId)).all()}


def _datos(sesion, codigo, numero, **otros):
    return {"nombre": "PROVEEDOR FICTICIO", "tipo_id_id": _ids(sesion)[codigo], "numero_id": numero, **otros}


def test_guardar_rechaza_cedula_y_ruc_natural_invalidos(sesion):
    buena = _cedula("171430710")
    mala = buena[:9] + str((int(buena[9]) + 1) % 10)
    assert servicios.validar_datos(sesion, _datos(sesion, "C", buena)) == []
    assert servicios.validar_datos(sesion, _datos(sesion, "R", buena + "001")) == []
    assert any("dígito verificador" in e for e in servicios.validar_datos(sesion, _datos(sesion, "C", mala)))
    assert any("cédula válida" in e for e in servicios.validar_datos(sesion, _datos(sesion, "R", mala + "001")))
    # El mensaje de largo de siempre se conserva y no se mezcla con el del verificador.
    errores = servicios.validar_datos(sesion, _datos(sesion, "C", "123"))
    assert errores == ["Un número de CEDULA debe tener 10 dígitos."]


def test_guardar_permite_ruc_de_sociedad_aunque_el_verificador_no_cuadre(sesion):
    malo = ruc_privada()[:9] + str((int(ruc_privada()[9]) + 1) % 10) + "001"
    assert servicios.validar_datos(sesion, _datos(sesion, "R", malo)) == []


def test_la_pantalla_de_validaciones_marca_lo_dudoso(sesion, personas):
    buena = _cedula("171430710")
    mala_c = buena[:9] + str((int(buena[9]) + 1) % 10)
    mala_s = ruc_privada()[:9] + str((int(ruc_privada()[9]) + 1) % 10) + "001"
    for nombre, tipo, numero in (("A", "C", mala_c), ("B", "R", mala_s), ("C", "R", ruc_privada())):
        servicios.crear_proveedor(sesion, _datos(sesion, tipo, numero, nombre=nombre), personas["creador"])
    sesion.commit()
    grupos = {g["clave"]: g for g in validaciones.revisar(sesion)}
    assert [c["proveedor"].nombre for c in grupos["id_invalido"]["casos"]] == ["A"]
    assert grupos["id_invalido"]["severidad"] == "alta"
    assert [c["proveedor"].nombre for c in grupos["id_dudoso"]["casos"]] == ["B"]  # el RUC bien formado (C) no aparece


def test_formulario_web_rechaza_cedula_mala_y_avisa_en_vivo(equipo, ids_catalogo):
    creador = equipo["creador"]
    mala = "1714307104"  # la referencia con el verificador cambiado
    respuesta = publicar(creador, "/proveedores/nuevo", formulario_proveedor(ids_catalogo, numero_id=mala, tipo_id_id=_id_cedula(equipo)))
    assert respuesta.status_code == 400 and "dígito verificador" in respuesta.text
    en_vivo = creador.get(
        "/proveedores/verificar", params={"tipo_id_id": _id_cedula(equipo), "numero_id": mala}, headers={"HX-Request": "true"}
    ).text
    assert "dígito verificador" in en_vivo and "aviso-error" in en_vivo
    # Un RUC de sociedad dudoso se muestra como alerta, no como error.
    dudoso = ruc_privada()[:9] + str((int(ruc_privada()[9]) + 1) % 10) + "001"
    en_vivo = creador.get(
        "/proveedores/verificar", params={"tipo_id_id": ids_catalogo["tipo_id"], "numero_id": dudoso}, headers={"HX-Request": "true"}
    ).text
    assert "aviso-alerta" in en_vivo and "aviso-error" not in en_vivo and "módulo 11" in en_vivo
    # Si el largo no es el correcto, el aviso en vivo lo deja a la pantalla (no repite el mensaje).
    corto = creador.get("/proveedores/verificar", params={"tipo_id_id": _id_cedula(equipo), "numero_id": "171"}, headers={"HX-Request": "true"}).text
    assert "aviso" not in corto


def _id_cedula(equipo):
    from app import db

    with db.SessionLocal() as s:
        return str(s.scalars(select(TipoId).where(TipoId.codigo == "C")).one().id)


def test_ruc_de_sociedad_dudoso_se_guarda_y_solo_advierte(equipo, ids_catalogo):
    """Un RUC de sociedad que no pasa el módulo 11 NO bloquea el alta ni la edición: se guarda con una advertencia."""
    from app.modelos import Proveedor

    creador = equipo["creador"]
    dudoso = ruc_privada()[:9] + str((int(ruc_privada()[9]) + 1) % 10) + "001"
    assert identificacion.revisar("R", dudoso).errores == []

    # Alta: se guarda (303), queda pendiente y se muestra la advertencia.
    respuesta = publicar(creador, "/proveedores/nuevo", formulario_proveedor(ids_catalogo, numero_id=dudoso))
    assert respuesta.status_code == 303
    ficha = creador.get(respuesta.headers["location"]).text
    assert "Proveedor creado" in ficha and "no pasó la verificación" in ficha and "aviso-alerta" in ficha
    assert "dígito verificador" in ficha  # también en el recuadro de avisos de validación de la ficha
    pid = int(respuesta.headers["location"].rsplit("/", 1)[1])
    from app import db

    with db.SessionLocal() as s:
        assert s.get(Proveedor, pid).numero_id == dudoso

    # Edición: guardar otra vez con el mismo RUC dudoso también funciona y vuelve a advertir.
    respuesta = publicar(creador, f"/proveedores/{pid}/editar", formulario_proveedor(ids_catalogo, numero_id=dudoso, notas="cambio"))
    assert respuesta.status_code == 303
    assert "no pasó la verificación" in creador.get(f"/proveedores/{pid}").text

    # Un RUC de sociedad correcto no genera la advertencia.
    bueno = publicar(creador, "/proveedores/nuevo", formulario_proveedor(ids_catalogo, numero_id=ruc_privada(), numero_cuenta="123", nombre="OTRA"))
    assert bueno.status_code == 303
    assert "no pasó la verificación" not in creador.get(bueno.headers["location"]).text


def test_al_aprobarse_un_proveedor_sale_de_validaciones(sesion, personas):
    """Aprobar = revisado: ya no aparece. Pero un pendiente sigue avisándose si repite datos de un aprobado."""
    dudoso = ruc_privada()[:9] + str((int(ruc_privada()[9]) + 1) % 10) + "001"
    ya_aprobado = servicios.crear_proveedor(
        sesion, _datos(sesion, "R", dudoso, nombre="APROBADO SA", numero_cuenta="555", tipo_cuenta_id=None), personas["creador"]
    )
    sesion.commit()
    assert [c["proveedor"].nombre for g in validaciones.revisar(sesion) if g["clave"] == "id_dudoso" for c in g["casos"]] == ["APROBADO SA"]

    servicios.aprobar(sesion, ya_aprobado, personas["aprobador"])
    sesion.commit()
    assert all(c["proveedor"].id != ya_aprobado.id for g in validaciones.revisar(sesion) for c in g["casos"])
    assert validaciones.avisos_de(sesion, ya_aprobado) == []

    # Un proveedor nuevo con el mismo RUC dudoso y la misma cuenta: se avisa, y el duplicado se detecta contra el aprobado.
    otro = servicios.crear_proveedor(
        sesion, _datos(sesion, "R", dudoso, nombre="NUEVO SA", numero_cuenta="555", tipo_cuenta_id=None), personas["creador"]
    )
    sesion.commit()
    grupos = {g["clave"]: g for g in validaciones.revisar(sesion)}
    assert [c["proveedor"].nombre for c in grupos["id_dudoso"]["casos"]] == ["NUEVO SA"]
    assert [c["proveedor"].nombre for c in grupos["id_duplicado"]["casos"]] == ["NUEVO SA"]
    assert "APROBADO SA" in grupos["id_duplicado"]["casos"][0]["detalle"]

    # Si a un aprobado se le cambia un dato sensible vuelve a Pendiente y reaparece.
    servicios.aprobar(sesion, otro, personas["aprobador"])
    servicios.aplicar_cambios(sesion, ya_aprobado, {"numero_cuenta": "999"}, personas["creador"])
    sesion.commit()
    assert ya_aprobado.estado_aprobacion == "pendiente"
    assert any(c["proveedor"].id == ya_aprobado.id for g in validaciones.revisar(sesion) for c in g["casos"])
