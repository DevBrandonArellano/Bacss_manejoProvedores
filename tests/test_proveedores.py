"""Alta manual de proveedores, validaciones e historial de cambios bancarios."""
from sqlalchemy import select

import ayudas
from app import servicios, validaciones
from app.modelos import APROBADO, PENDIENTE, RECHAZADO, Historial, Proveedor


def test_alta_manual_conserva_ceros_a_la_izquierda(sesion, personas):
    datos = ayudas.datos_proveedor(sesion, numero_id="0990000000001", numero_cuenta="0012345678")
    assert servicios.validar_datos(sesion, datos) == []
    p = servicios.crear_proveedor(sesion, datos, personas["creador"])
    sesion.commit()
    sesion.expire_all()

    guardado = sesion.get(Proveedor, p.id)
    assert guardado.numero_id == "0990000000001"
    assert guardado.numero_cuenta == "0012345678"
    assert isinstance(guardado.numero_id, str) and isinstance(guardado.numero_cuenta, str)
    assert guardado.estado_aprobacion == PENDIENTE
    assert guardado.creado_por_id == personas["creador"].id
    assert guardado.activo is True


def test_la_app_arranca_sin_proveedores(sesion):
    assert sesion.scalars(select(Proveedor)).all() == []


def test_numeros_se_tratan_como_texto_sin_espacios():
    assert servicios.sin_espacios(" 00 123 ") == "00123"
    assert servicios.sin_espacios("") is None
    assert servicios.sin_espacios(None) is None
    assert servicios.limpiar("  Ferretería   Inventada  ") == "Ferretería Inventada"
    assert servicios.normalizar("  Ferretería   Inventada ") == "FERRETERIA INVENTADA"


def test_validaciones_del_formulario(sesion, personas):
    servicios.crear_proveedor(sesion, ayudas.datos_proveedor(sesion), personas["creador"])
    sesion.commit()

    def errores(**cambios):
        return " ".join(servicios.validar_datos(sesion, ayudas.datos_proveedor(sesion, **cambios)))

    assert "obligatorio" in errores(nombre=None, numero_id="0990000000002")
    assert "Ya existe" in errores(nombre="OTRO NOMBRE")  # mismo tipo y número de ID
    assert "13 dígitos" in errores(numero_id="099000000001")  # RUC de 12
    assert "13 dígitos" in errores(numero_id="09900000000A1")
    cedula = ayudas.tipo_id(sesion, "C").id
    assert "10 dígitos" in errores(tipo_id_id=cedula, numero_id="012345678")
    assert errores(tipo_id_id=cedula, numero_id="0123456789") == ""
    assert "correo" in errores(numero_id="0990000000002", correo="sin-arroba.example")
    assert errores(numero_id="0990000000002", correo="a@uno.example; b@dos.example") == ""
    assert "tipo de cuenta" in errores(numero_id="0990000000002", tipo_cuenta_id=None)
    assert "días de crédito" in errores(numero_id="0990000000002", credito_tipo="dias", credito_valor=None)
    assert "no existe" in errores(numero_id="0990000000002", banco_id=999999)


def test_editar_el_mismo_proveedor_no_choca_con_su_propia_identificacion(sesion, personas):
    p = servicios.crear_proveedor(sesion, ayudas.datos_proveedor(sesion), personas["creador"])
    sesion.commit()
    assert servicios.validar_datos(sesion, ayudas.datos_proveedor(sesion), proveedor_id=p.id) == []


def test_historial_registra_quien_cambio_la_cuenta(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    cambiados = servicios.aplicar_cambios(sesion, p, {"numero_cuenta": "0099999999"}, personas["admin"])
    sesion.commit()

    assert cambiados == ["numero_cuenta"]
    movimiento = sesion.scalars(
        select(Historial).where(Historial.proveedor_id == p.id, Historial.campo == "Número de cuenta")
    ).one()
    assert movimiento.valor_anterior == "0012345678"
    assert movimiento.valor_nuevo == "0099999999"
    assert movimiento.sensible is True
    assert movimiento.usuario_id == personas["admin"].id
    assert "admin" in movimiento.usuario_nombre
    assert movimiento.fecha is not None


def test_cambiar_la_cuenta_devuelve_a_pendiente(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    assert p.estado_aprobacion == APROBADO

    servicios.aplicar_cambios(sesion, p, {"numero_cuenta": "0099999999"}, personas["creador"])
    sesion.commit()

    assert p.estado_aprobacion == PENDIENTE
    assert p.aprobado_por_id is None and p.aprobado_en is None
    assert p.modificado_por_id == personas["creador"].id


def test_cambiar_el_banco_o_la_identificacion_devuelve_a_pendiente(sesion, personas):
    otro_banco = ayudas.banco_de_prueba(sesion, "0043", "OTRO BANCO INVENTADO")
    for i, cambio in enumerate(
        [{"banco_id": otro_banco.id}, {"numero_id": "0990000000777"}, {"nombre": "NOMBRE NUEVO INVENTADO"},
         {"tipo_cuenta_id": ayudas.tipo_cuenta(sesion, "AHO").id}]
    ):
        p = ayudas.proveedor_aprobado(
            sesion, personas["creador"], personas["aprobador"], numero_id=f"099000000{i:04d}", nombre=f"PROVEEDOR {i}"
        )
        servicios.aplicar_cambios(sesion, p, cambio, personas["creador"])
        sesion.commit()
        assert p.estado_aprobacion == PENDIENTE, cambio


def test_cambios_no_sensibles_no_quitan_la_aprobacion(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    cambiados = servicios.aplicar_cambios(
        sesion,
        p,
        {"correo": "nuevo@ferreteria-inventada.example", "notas": "Llamar antes de pagar", "registrado_banco": True,
         "credito_tipo": "fin_mes", "credito_valor": None},
        personas["creador"],
    )
    sesion.commit()
    assert set(cambiados) == {"correo", "notas", "registrado_banco", "credito"}
    assert p.estado_aprobacion == APROBADO


def test_guardar_sin_cambios_no_deja_historial(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    antes = len(sesion.scalars(select(Historial).where(Historial.proveedor_id == p.id)).all())
    assert servicios.aplicar_cambios(sesion, p, ayudas.datos_proveedor(sesion), personas["admin"]) == []
    sesion.commit()
    assert len(sesion.scalars(select(Historial).where(Historial.proveedor_id == p.id)).all()) == antes
    assert p.modificado_por_id == personas["creador"].id


def test_corregir_un_rechazado_lo_reenvia_a_aprobacion(sesion, personas):
    p = servicios.crear_proveedor(sesion, ayudas.datos_proveedor(sesion), personas["creador"])
    servicios.rechazar(sesion, p, personas["aprobador"], "La cuenta no coincide con el certificado")
    sesion.commit()
    assert p.estado_aprobacion == RECHAZADO

    servicios.aplicar_cambios(sesion, p, {"correo": "corregido@ferreteria-inventada.example"}, personas["creador"])
    sesion.commit()
    assert p.estado_aprobacion == PENDIENTE
    assert p.motivo_rechazo is None


def test_desactivar_no_borra(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    servicios.aplicar_cambios(sesion, p, {"activo": False}, personas["creador"])
    sesion.commit()
    assert sesion.get(Proveedor, p.id) is not None
    assert p.activo is False
    assert p.estado_aprobacion == APROBADO


def test_validaciones_detectan_datos_sospechosos(sesion, personas):
    creador = personas["creador"]
    base = servicios.crear_proveedor(sesion, ayudas.datos_proveedor(sesion), creador)
    misma_cuenta = servicios.crear_proveedor(
        sesion, ayudas.datos_proveedor(sesion, nombre="OTRO CON LA MISMA CUENTA", numero_id="0990000000002"), creador
    )
    incompleto = servicios.crear_proveedor(
        sesion,
        ayudas.datos_proveedor(
            sesion, nombre="PROVEEDOR INCOMPLETO", numero_id=None, tipo_id_id=None, numero_cuenta=None,
            tipo_cuenta_id=None, banco_id=None, correo=None, credito_tipo=None, credito_valor=None,
        ),
        creador,
    )
    correo_malo = servicios.crear_proveedor(
        sesion,
        ayudas.datos_proveedor(sesion, nombre="CORREO MALO", numero_id="0990000000003", numero_cuenta="0011111111",
                               correo="sin-arroba"),
        creador,
    )
    id_corto = servicios.crear_proveedor(
        sesion,
        ayudas.datos_proveedor(sesion, nombre="RUC CORTO", numero_id="099000001", numero_cuenta="0022222222"),
        creador,
    )
    sesion.commit()

    grupos = {g["clave"]: {c["proveedor"].id for c in g["casos"]} for g in validaciones.revisar(sesion)}

    assert grupos["cuenta_duplicada"] == {base.id, misma_cuenta.id}
    assert grupos["sin_cuenta"] == {incompleto.id}
    assert grupos["sin_banco"] == {incompleto.id}
    assert grupos["sin_id"] == {incompleto.id}
    assert grupos["sin_correo"] == {incompleto.id}
    assert grupos["sin_credito"] == {incompleto.id}
    assert grupos["correo_malo"] == {correo_malo.id}
    assert grupos["largo_id"] == {id_corto.id}
    # el mismo correo en 3 proveedores (base, misma_cuenta, id_corto) se avisa
    assert grupos["correo_compartido"] == {base.id, misma_cuenta.id, id_corto.id}
    assert "id_duplicado" not in grupos

    avisos = {a["titulo"] for a in validaciones.avisos_de(sesion, incompleto)}
    assert "Sin banco" in avisos and "Sin identificación" in avisos


def test_validaciones_ignoran_desactivados(sesion, personas):
    p = servicios.crear_proveedor(
        sesion, ayudas.datos_proveedor(sesion, banco_id=None), personas["creador"]
    )
    servicios.aplicar_cambios(sesion, p, {"activo": False}, personas["creador"])
    sesion.commit()
    assert validaciones.revisar(sesion) == []
