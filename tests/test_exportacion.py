"""Archivo de pago masivo: mismo formato que la hoja de pago del Excel original."""
import io
from datetime import date

import openpyxl
import pytest

import ayudas
from app import exportacion, servicios

ENCABEZADOS_ESPERADOS = [
    "NOMBRE",
    "TIPO",
    "CONTRAPARTIDA",
    "MONEDA",
    "VALOR",
    "FORMA DE PAGO",
    "TIPO CTA",
    "NUMERO CTA",
    "REFERENCIA",
    "TIPO ID",
    "NUMERO ID",
    "NOMBRE BENEFICIARIO",
    "CODIGOS BANCOS",
    "correo",
    "DIAS CREDITO",
]


def _leer(libro):
    hoja = openpyxl.load_workbook(io.BytesIO(exportacion.a_bytes(libro)))[exportacion.HOJA_PAGO]
    filas = list(hoja.iter_rows(values_only=True))
    return hoja, filas[0], [dict(zip(filas[0], fila)) for fila in filas[1:]]


def test_encabezados_identicos_a_la_hoja_de_pago():
    assert exportacion.ENCABEZADOS_PAGO == ENCABEZADOS_ESPERADOS


def test_fila_de_pago(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    f = ayudas.factura(sesion, p, personas["creador"], numero="001-001-000000123", valor="1250.50")

    hoja, encabezados, filas = _leer(exportacion.libro_pago_masivo([f], "1"))

    assert hoja.title == "Hoja 1"
    assert list(encabezados) == ENCABEZADOS_ESPERADOS
    assert len(filas) == 1
    fila = filas[0]
    assert fila["NOMBRE"] == "FERRETERIA INVENTADA S.A."
    assert fila["TIPO"] == "PA"
    assert fila["CONTRAPARTIDA"] == 1
    assert fila["MONEDA"] == "USD"
    assert fila["VALOR"] == pytest.approx(1250.50)
    assert fila["FORMA DE PAGO"] == "CTA"
    assert fila["TIPO CTA"] == "CTE"
    assert fila["NUMERO CTA"] == "0012345678"
    assert fila["REFERENCIA"] == "PAGO FAC 001-001-000000123 FERRETERIA INVENTADA S.A."
    assert fila["TIPO ID"] == "RUC"
    assert fila["NUMERO ID"] == "0990000000001"
    assert fila["NOMBRE BENEFICIARIO"] == "FERRETERIA INVENTADA S.A."
    assert fila["CODIGOS BANCOS"] == "0042"
    assert fila["correo"] == "pagos@ferreteria-inventada.example"
    assert fila["DIAS CREDITO"] == "30"


def test_cuenta_id_y_codigo_de_banco_van_como_texto(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    f = ayudas.factura(sesion, p, personas["creador"])
    hoja, encabezados, _ = _leer(exportacion.libro_pago_masivo([f], "1"))
    for nombre in ("NUMERO CTA", "NUMERO ID", "CODIGOS BANCOS"):
        celda = hoja.cell(2, list(encabezados).index(nombre) + 1)
        assert isinstance(celda.value, str), nombre
        assert celda.value.startswith("0"), f"{nombre} perdió los ceros a la izquierda"
        assert celda.number_format == "@", nombre
        assert celda.data_type == "s", nombre


def test_varias_facturas_y_condiciones_de_credito(sesion, personas):
    creador, aprobador = personas["creador"], personas["aprobador"]
    contado = ayudas.proveedor_aprobado(
        sesion, creador, aprobador, nombre="PROVEEDOR CONTADO", numero_id="0990000000002", numero_cuenta="0011111111",
        credito_tipo="dias", credito_valor=0, tipo_id_id=ayudas.tipo_id(sesion, "C").id,
        tipo_cuenta_id=ayudas.tipo_cuenta(sesion, "AHO").id,
    )
    fin_mes = ayudas.proveedor_aprobado(
        sesion, creador, aprobador, nombre="PROVEEDOR FIN DE MES", numero_id="0990000000003", numero_cuenta="0022222222",
        credito_tipo="fin_mes", credito_valor=None,
    )
    dia_fijo = ayudas.proveedor_aprobado(
        sesion, creador, aprobador, nombre="PROVEEDOR DIA FIJO", numero_id="0990000000004", numero_cuenta="0033333333",
        credito_tipo="dia_fijo", credito_valor=29,
    )
    facturas = [
        ayudas.factura(sesion, contado, creador, numero="F-1", valor="10"),
        ayudas.factura(sesion, fin_mes, creador, numero="F-2", valor="0.99"),
        ayudas.factura(sesion, dia_fijo, creador, numero="F-3", valor="100000.01"),
    ]

    _, _, filas = _leer(exportacion.libro_pago_masivo(facturas, "1"))

    assert [fila["DIAS CREDITO"] for fila in filas] == ["CONTADO", "FIN DE MES", "29 DE CADA MES"]
    assert [fila["VALOR"] for fila in filas] == [pytest.approx(10.0), pytest.approx(0.99), pytest.approx(100000.01)]
    assert filas[0]["TIPO ID"] == "CEDULA"
    assert filas[0]["TIPO CTA"] == "AHO"
    assert [fila["REFERENCIA"] for fila in filas] == [
        "PAGO FAC F-1 PROVEEDOR CONTADO",
        "PAGO FAC F-2 PROVEEDOR FIN DE MES",
        "PAGO FAC F-3 PROVEEDOR DIA FIJO",
    ]


def test_contrapartida_configurable(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    f = ayudas.factura(sesion, p, personas["creador"])
    _, _, filas = _leer(exportacion.libro_pago_masivo([f], "7"))
    assert filas[0]["CONTRAPARTIDA"] == 7
    _, _, filas = _leer(exportacion.libro_pago_masivo([f], "0012"))
    assert filas[0]["CONTRAPARTIDA"] == "0012"

    assert servicios.contrapartida(sesion) == servicios.CONTRAPARTIDA_DEFECTO
    servicios.cfg_guardar(sesion, "contrapartida", "5")
    sesion.commit()
    assert servicios.contrapartida(sesion) == "5"


def test_proveedor_sin_aprobar_no_se_exporta(sesion, personas):
    p = servicios.crear_proveedor(sesion, ayudas.datos_proveedor(sesion), personas["creador"])
    sesion.commit()
    f = ayudas.factura(sesion, p, personas["creador"])

    assert "no está revisado" in exportacion.motivo_bloqueo(f)
    with pytest.raises(ValueError):
        exportacion.libro_pago_masivo([f], "1")

    servicios.aprobar(sesion, p, personas["aprobador"])
    sesion.commit()
    assert exportacion.motivo_bloqueo(f) is None


def test_cambiar_la_cuenta_bloquea_la_exportacion_hasta_reaprobar(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    f = ayudas.factura(sesion, p, personas["creador"])
    assert exportacion.motivo_bloqueo(f) is None

    servicios.aplicar_cambios(sesion, p, {"numero_cuenta": "0099999999"}, personas["creador"])
    sesion.commit()
    assert "no está revisado" in exportacion.motivo_bloqueo(f)

    servicios.aprobar(sesion, p, personas["aprobador"])
    sesion.commit()
    _, _, filas = _leer(exportacion.libro_pago_masivo([f], "1"))
    assert filas[0]["NUMERO CTA"] == "0099999999"


def test_otros_bloqueos(sesion, personas):
    creador, aprobador = personas["creador"], personas["aprobador"]
    p = ayudas.proveedor_aprobado(sesion, creador, aprobador)
    f = ayudas.factura(sesion, p, creador)

    servicios.aplicar_cambios(sesion, p, {"activo": False}, creador)
    assert "desactivado" in exportacion.motivo_bloqueo(f)
    servicios.aplicar_cambios(sesion, p, {"activo": True}, creador)
    assert exportacion.motivo_bloqueo(f) is None

    servicios.marcar_pagada(sesion, f, creador, date(2026, 3, 20))
    assert "pagada" in exportacion.motivo_bloqueo(f)

    sin_banco = ayudas.proveedor_aprobado(
        sesion, creador, aprobador, nombre="SIN BANCO", numero_id="0990000000009", numero_cuenta="0044444444", banco_id=None
    )
    assert "banco" in exportacion.motivo_bloqueo(ayudas.factura(sesion, sin_banco, creador, numero="F-9"))


def test_un_nombre_que_empieza_con_igual_no_se_convierte_en_formula(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"], nombre="=1+1")
    f = ayudas.factura(sesion, p, personas["creador"])
    hoja, encabezados, filas = _leer(exportacion.libro_pago_masivo([f], "1"))
    assert filas[0]["NOMBRE"] == "=1+1"
    assert hoja.cell(2, 1).data_type == "s"


def test_exportar_listado_de_proveedores(sesion, personas):
    ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    from sqlalchemy import select

    from app.modelos import Proveedor

    proveedores = sesion.scalars(select(Proveedor)).all()
    empresa = personas["creador"].empresa
    ayudas.con_credito(sesion, proveedores[0], empresa, personas["creador"], "dias", 30)
    libro = openpyxl.load_workbook(
        io.BytesIO(exportacion.a_bytes(exportacion.libro_proveedores(proveedores, [empresa])))
    )
    filas = list(libro["Proveedores"].iter_rows(values_only=True))
    esperado = list(exportacion.ENCABEZADOS_PROVEEDORES)
    esperado.insert(esperado.index("CORREO") + 1, "CREDITO EMPRESA A")
    assert list(filas[0]) == esperado and "DIAS CREDITO" not in esperado
    fila = dict(zip(filas[0], filas[1]))
    assert fila["NUMERO ID"] == "0990000000001"
    assert fila["NUMERO CTA"] == "0012345678"
    assert fila["CODIGO BANCO"] == "0042"
    assert fila["ESTADO REVISION"] == "Revisado"
    assert fila["CREDITO EMPRESA A"] == "30"
