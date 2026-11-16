"""Cálculo de vencimientos: un error aquí hace pagar tarde o no avisar."""
from datetime import date

import pytest

from app import credito
from app.credito import DIA_FIJO, DIAS, FIN_MES, calcular_vencimiento, interpretar


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("CONTADO", (DIAS, 0)),
        ("contado", (DIAS, 0)),
        ("conTADO ", (DIAS, 0)),
        ("30", (DIAS, 30)),
        (30, (DIAS, 30)),
        ("15 DIAS", (DIAS, 15)),
        ("15 dias", (DIAS, 15)),
        ("30 días", (DIAS, 30)),
        ("8 DIAS", (DIAS, 8)),
        ("25", (DIAS, 25)),
        ("FIN DE MES", (FIN_MES, None)),
        ("fin de mes ", (FIN_MES, None)),
        ("29 DE CADA MES", (DIA_FIJO, 29)),
        ("", (None, None)),
        (None, (None, None)),
        ("A CONVENIR", (None, None)),
        ("45 DE CADA MES", (None, None)),
    ],
)
def test_interpretar_variantes_del_excel(texto, esperado):
    assert interpretar(texto) == esperado


def test_dias_desde_la_factura():
    assert calcular_vencimiento(date(2026, 3, 10), DIAS, 30) == date(2026, 4, 9)
    assert calcular_vencimiento(date(2026, 12, 20), DIAS, 15) == date(2027, 1, 4)


def test_contado_vence_el_mismo_dia():
    assert calcular_vencimiento(date(2026, 3, 10), DIAS, 0) == date(2026, 3, 10)


def test_sin_condicion_se_trata_como_contado():
    assert calcular_vencimiento(date(2026, 3, 10), None, None) == date(2026, 3, 10)


@pytest.mark.parametrize(
    "fecha, esperado",
    [
        (date(2026, 1, 15), date(2026, 1, 31)),
        (date(2026, 4, 1), date(2026, 4, 30)),
        (date(2026, 4, 30), date(2026, 4, 30)),
        (date(2026, 2, 10), date(2026, 2, 28)),  # febrero normal
        (date(2028, 2, 10), date(2028, 2, 29)),  # febrero bisiesto
        (date(2026, 12, 31), date(2026, 12, 31)),
    ],
)
def test_fin_de_mes(fecha, esperado):
    assert calcular_vencimiento(fecha, FIN_MES, None) == esperado


@pytest.mark.parametrize(
    "fecha, dia, esperado",
    [
        (date(2026, 3, 10), 29, date(2026, 3, 29)),  # antes del día: ese mismo mes
        (date(2026, 3, 29), 29, date(2026, 3, 29)),  # el mismo día: vence ese día
        (date(2026, 3, 30), 29, date(2026, 4, 29)),  # ya pasó: mes siguiente
        (date(2026, 12, 30), 29, date(2027, 1, 29)),  # cambio de año
        (date(2026, 2, 10), 29, date(2026, 2, 28)),  # febrero no tiene 29: último día
        (date(2028, 2, 10), 29, date(2028, 2, 29)),  # bisiesto sí lo tiene
        (date(2026, 1, 30), 29, date(2026, 2, 28)),  # pasa a febrero, que no tiene 29
        (date(2026, 4, 10), 31, date(2026, 4, 30)),  # abril no tiene 31
        (date(2026, 1, 31), 31, date(2026, 1, 31)),
        (date(2026, 5, 5), 1, date(2026, 6, 1)),
    ],
)
def test_dia_fijo_del_mes(fecha, dia, esperado):
    assert calcular_vencimiento(fecha, DIA_FIJO, dia) == esperado


def test_textos():
    assert credito.texto(DIAS, 0) == "Contado"
    assert credito.texto(DIAS, 30) == "30 días"
    assert credito.texto(FIN_MES, None) == "Fin de mes"
    assert credito.texto(DIA_FIJO, 29) == "Día 29 de cada mes"
    assert credito.texto(None, None) == "Sin definir"
    assert credito.texto_excel(DIAS, 0) == "CONTADO"
    assert credito.texto_excel(DIAS, 30) == "30"
    assert credito.texto_excel(FIN_MES, None) == "FIN DE MES"
    assert credito.texto_excel(DIA_FIJO, 29) == "29 DE CADA MES"


def test_validar():
    assert credito.validar(None, None) is None
    assert credito.validar(DIAS, 30) is None
    assert credito.validar(DIAS, None) is not None
    assert credito.validar(DIAS, 400) is not None
    assert credito.validar(FIN_MES, None) is None
    assert credito.validar(DIA_FIJO, 31) is None
    assert credito.validar(DIA_FIJO, 0) is not None
    assert credito.validar("otra", 1) is not None
