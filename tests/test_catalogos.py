"""Catálogos: semilla de instituciones financieras (códigos oficiales) y carga desde Excel."""
import io
from collections import Counter

import openpyxl
import pytest
from sqlalchemy import func, select

import ayudas
from app import catalogos, exportacion, servicios
from app.modelos import Banco, Proveedor, TipoCuenta, TipoId
from app.servicios import ErrorNegocio


def _contar(sesion, modelo) -> int:
    return sesion.scalar(select(func.count()).select_from(modelo))


# ---------------------------------------------------------------- semilla


def test_la_semilla_se_carga_completa_y_con_los_mismos_codigos(sesion):
    pares = catalogos.leer_semilla()
    assert len(pares) > 400, "la semilla de instituciones financieras debería traer el catálogo completo"
    assert _contar(sesion, Banco) == len(pares)
    en_base = Counter((b.codigo, b.nombre) for b in sesion.scalars(select(Banco)).all())
    assert en_base == Counter(pares), "códigos y nombres deben quedar idénticos a los del archivo semilla"


def test_los_codigos_de_la_semilla_son_texto_sin_reformatear(sesion):
    for codigo, nombre in catalogos.leer_semilla():
        assert codigo == codigo.strip() and codigo != ""
        assert nombre == nombre.strip() and nombre != ""
    pichincha = sesion.scalars(select(Banco).where(Banco.nombre == "BANCO PICHINCHA C.A.")).one()
    assert pichincha.codigo == "10"
    assert isinstance(pichincha.codigo, str)


def test_los_codigos_repetidos_del_catalogo_oficial_se_conservan(sesion):
    por_codigo = Counter(codigo for codigo, _ in catalogos.leer_semilla())
    repetidos = {codigo for codigo, veces in por_codigo.items() if veces > 1}
    assert repetidos, "el catálogo oficial trae códigos compartidos por dos instituciones"
    for codigo in repetidos:
        en_base = sesion.scalars(select(Banco).where(Banco.codigo == codigo)).all()
        assert len(en_base) == por_codigo[codigo], f"no debe descartarse ninguna institución del código {codigo}"


def test_la_siembra_no_duplica_ni_pisa_cambios_manuales(sesion):
    total = _contar(sesion, Banco)
    banco = sesion.scalars(select(Banco).where(Banco.codigo == "10")).first()
    banco.nombre = "NOMBRE CAMBIADO A MANO"
    banco.nombre_norm = servicios.normalizar(banco.nombre)
    banco.activo = False
    sesion.commit()

    catalogos.preparar_bd(sesion)  # como si la app se reiniciara
    assert catalogos.sembrar_bancos(sesion) == 0

    assert _contar(sesion, Banco) == total
    sesion.refresh(banco)
    assert banco.nombre == "NOMBRE CAMBIADO A MANO"
    assert banco.activo is False


def test_tipos_sembrados(sesion):
    assert {(t.codigo, t.nombre) for t in sesion.scalars(select(TipoId)).all()} == {
        ("C", "CEDULA"),
        ("R", "RUC"),
        ("P", "PASAPORTE"),
    }
    assert {(t.codigo, t.nombre) for t in sesion.scalars(select(TipoCuenta)).all()} == {
        ("AHO", "AHORROS"),
        ("CTE", "CORRIENTE"),
    }


def test_un_codigo_de_la_semilla_se_exporta_sin_alterarse(sesion, personas):
    banco = sesion.scalars(select(Banco).where(Banco.nombre == "BANCO PICHINCHA C.A.")).one()
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"], banco_id=banco.id)
    f = ayudas.factura(sesion, p, personas["creador"])
    libro = openpyxl.load_workbook(io.BytesIO(exportacion.a_bytes(exportacion.libro_pago_masivo([f], "1"))))
    hoja = libro[exportacion.HOJA_PAGO]
    columna = exportacion.ENCABEZADOS_PAGO.index("CODIGOS BANCOS") + 1
    celda = hoja.cell(2, columna)
    assert celda.value == banco.codigo == "10"
    assert isinstance(celda.value, str)
    assert celda.number_format == "@"


# ---------------------------------------------------------------- carga desde Excel


def _excel_catalogos(ruta, bancos, tipos_extra=()):
    """Excel inventado con la misma disposición: hoja de proveedores + hoja de catálogos «Hoja2»."""
    libro = openpyxl.Workbook()
    maestro = libro.active
    maestro.title = "MAESTRO"
    # Si la carga leyera esta hoja, aparecería este banco falso en el catálogo.
    maestro.append([None, "DÍAS CREDITO ", "REGISTRADO", "TIPO ID", "NUMERO ID", None, "Código Banco", "Nombre del Banco"])
    maestro.append(["PROVEEDOR QUE NO DEBE LEERSE", "30", "OK", "RUC", "0999999999001", None, 7777, "BANCO DE LA HOJA EQUIVOCADA"])

    hoja = libro.create_sheet("Hoja2")
    hoja.append(["TIPO ID", None, None, "Código de instituciones financieras"])
    hoja.append(["C", "CEDULA", None, "Código Banco", "Nombre del Banco", None, "Código Banco", "Nombre del Banco"])
    tipos = [("R", "RUC"), ("P", "PASAPORTE"), (None, None), ("AHO", "AHORROS"), ("CTE", "CORRIENTE")] + list(tipos_extra)
    for i in range(max(len(tipos), len(bancos))):
        codigo_tipo, nombre_tipo = tipos[i] if i < len(tipos) else (None, None)
        codigo, nombre = bancos[i] if i < len(bancos) else (None, None)
        # la lista corta de la derecha repite solo la primera institución
        corto = bancos[0] if i == 0 else (None, None)
        hoja.append([codigo_tipo, nombre_tipo, None, codigo, nombre, codigo, corto[0], corto[1]])
    libro.save(ruta)
    return ruta


BANCOS_INVENTADOS = [
    (9001, "BANCO INVENTADO UNO"),
    (9002, "  COOPERATIVA INVENTADA DOS  "),
    (9002, "COOPERATIVA INVENTADA TRES"),  # mismo código que la anterior: se conservan las dos
    ("0077", "BANCO CON CEROS A LA IZQUIERDA"),
    (10, "BANCO PICHINCHA C.A."),  # ya viene en la semilla
]


def test_carga_de_catalogos_desde_excel(sesion, tmp_path):
    ruta = _excel_catalogos(tmp_path / "catalogos.xlsx", BANCOS_INVENTADOS, tipos_extra=[("X", "CARNET INVENTADO")])
    antes = _contar(sesion, Banco)

    resumen = catalogos.cargar_desde_excel(sesion, ruta)

    assert resumen.bancos_agregados == 4
    assert resumen.bancos_existentes == 2  # Pichincha (semilla) y la repetición de la lista corta
    assert resumen.tipos_id_agregados == 1
    assert resumen.tipos_cuenta_agregados == 0
    assert _contar(sesion, Banco) == antes + 4
    assert any("9002" in aviso for aviso in resumen.avisos), "debe avisar del código compartido"

    codigos = {b.nombre: b.codigo for b in sesion.scalars(select(Banco).where(Banco.codigo.in_(["9001", "9002", "0077"]))).all()}
    assert codigos == {
        "BANCO INVENTADO UNO": "9001",
        "COOPERATIVA INVENTADA DOS": "9002",  # solo se recortan los espacios de los extremos
        "COOPERATIVA INVENTADA TRES": "9002",
        "BANCO CON CEROS A LA IZQUIERDA": "0077",  # el código no se reformatea
    }
    assert sesion.scalars(select(TipoId).where(TipoId.codigo == "X")).one().nombre == "CARNET INVENTADO"


def test_la_carga_no_lee_la_hoja_de_proveedores(sesion, tmp_path):
    ruta = _excel_catalogos(tmp_path / "catalogos.xlsx", BANCOS_INVENTADOS)
    catalogos.cargar_desde_excel(sesion, ruta)
    assert _contar(sesion, Proveedor) == 0
    assert sesion.scalars(select(Banco).where(Banco.codigo == "7777")).first() is None
    assert sesion.scalars(select(Banco).where(Banco.nombre == "BANCO DE LA HOJA EQUIVOCADA")).first() is None


def test_repetir_la_carga_no_duplica(sesion, tmp_path):
    ruta = _excel_catalogos(tmp_path / "catalogos.xlsx", BANCOS_INVENTADOS, tipos_extra=[("X", "CARNET INVENTADO")])
    catalogos.cargar_desde_excel(sesion, ruta)
    total_bancos, total_tipos = _contar(sesion, Banco), _contar(sesion, TipoId)

    resumen = catalogos.cargar_desde_excel(sesion, ruta)

    assert resumen.bancos_agregados == 0
    assert resumen.bancos_existentes == 6
    assert resumen.tipos_id_agregados == 0
    assert _contar(sesion, Banco) == total_bancos
    assert _contar(sesion, TipoId) == total_tipos


def test_la_carga_no_cambia_un_codigo_existente(sesion, tmp_path):
    ruta = _excel_catalogos(tmp_path / "otro.xlsx", [(5555, "BANCO PICHINCHA C.A.")])
    resumen = catalogos.cargar_desde_excel(sesion, ruta)
    assert resumen.bancos_agregados == 0
    assert any("no se cambió" in aviso for aviso in resumen.avisos)
    assert sesion.scalars(select(Banco).where(Banco.nombre == "BANCO PICHINCHA C.A.")).one().codigo == "10"


def test_archivo_sin_hoja_de_catalogos(sesion, tmp_path):
    libro = openpyxl.Workbook()
    libro.active.title = "OTRA"
    ruta = tmp_path / "sin-hoja.xlsx"
    libro.save(ruta)
    with pytest.raises(ErrorNegocio):
        catalogos.cargar_desde_excel(sesion, ruta)


def test_archivo_que_no_es_excel(sesion, tmp_path):
    ruta = tmp_path / "falso.xlsx"
    ruta.write_text("esto no es un excel", encoding="utf-8")
    with pytest.raises(ErrorNegocio):
        catalogos.cargar_desde_excel(sesion, ruta)
