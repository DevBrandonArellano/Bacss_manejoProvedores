"""Condiciones de crédito y cálculo de la fecha de vencimiento.

Tres tipos de condición:
- "dias":     N días después de la fecha de la factura (CONTADO = 0 días).
- "fin_mes":  último día del mes de la factura.
- "dia_fijo": un día fijo del mes (p. ej. el 29 de cada mes).
"""
import calendar
import re
import unicodedata
from datetime import date, timedelta
from typing import Optional, Tuple

DIAS = "dias"
FIN_MES = "fin_mes"
DIA_FIJO = "dia_fijo"

TIPOS = {DIAS: "Días desde la factura", FIN_MES: "Fin de mes", DIA_FIJO: "Día fijo del mes"}


def _normalizar(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().upper()


def interpretar(texto) -> Tuple[Optional[str], Optional[int]]:
    """Convierte el texto libre del Excel en (tipo, valor). (None, None) si no se reconoce."""
    t = _normalizar(texto)
    if not t:
        return None, None
    if "CONTADO" in t:
        return DIAS, 0
    if "FIN DE MES" in t or "FIN MES" in t or t == "FDM":
        return FIN_MES, None
    m = re.fullmatch(r"(?:EL |DIA |LOS )?(\d{1,2}) DE CADA MES", t) or re.fullmatch(r"CADA (\d{1,2})", t)
    if m:
        dia = int(m.group(1))
        return (DIA_FIJO, dia) if 1 <= dia <= 31 else (None, None)
    m = re.fullmatch(r"(\d{1,3})(?:[.,]0+)?(?: ?(?:DIAS?|D))?", t)
    if m:
        return DIAS, int(m.group(1))
    return None, None


def validar(tipo, valor) -> Optional[str]:
    """Devuelve un mensaje de error si la condición no es válida."""
    if not tipo:
        return None
    if tipo == DIAS:
        if valor is None or not 0 <= valor <= 365:
            return "Los días de crédito deben estar entre 0 y 365."
    elif tipo == DIA_FIJO:
        if valor is None or not 1 <= valor <= 31:
            return "El día fijo del mes debe estar entre 1 y 31."
    elif tipo != FIN_MES:
        return "Condición de crédito desconocida."
    return None


def texto(tipo, valor) -> str:
    """Texto para mostrar en pantalla."""
    if tipo == DIAS:
        if not valor:
            return "Contado"
        return f"{valor} días"
    if tipo == FIN_MES:
        return "Fin de mes"
    if tipo == DIA_FIJO:
        return f"Día {valor} de cada mes"
    return "Sin definir"


def texto_excel(tipo, valor) -> str:
    """Texto para la columna DIAS CREDITO de los archivos exportados."""
    if tipo == DIAS:
        return "CONTADO" if not valor else str(valor)
    if tipo == FIN_MES:
        return "FIN DE MES"
    if tipo == DIA_FIJO:
        return f"{valor} DE CADA MES"
    return ""


def _ultimo_dia(anio: int, mes: int) -> int:
    return calendar.monthrange(anio, mes)[1]


def calcular_vencimiento(fecha: date, tipo, valor) -> date:
    """Fecha de vencimiento de una factura emitida en `fecha`.

    - Sin condición definida se trata como contado (vence el mismo día).
    - Día fijo: si la factura es de ese día o anterior, vence ese mes; si es
      posterior, vence el mes siguiente. Si el mes no tiene ese día (p. ej. el
      31 en febrero) se usa el último día del mes.
    """
    if tipo == DIAS:
        return fecha + timedelta(days=int(valor or 0))
    if tipo == FIN_MES:
        return date(fecha.year, fecha.month, _ultimo_dia(fecha.year, fecha.month))
    if tipo == DIA_FIJO:
        dia = int(valor or 1)
        en_mes = date(fecha.year, fecha.month, min(dia, _ultimo_dia(fecha.year, fecha.month)))
        if en_mes >= fecha:
            return en_mes
        anio, mes = (fecha.year + 1, 1) if fecha.month == 12 else (fecha.year, fecha.month + 1)
        return date(anio, mes, min(dia, _ultimo_dia(anio, mes)))
    return fecha
