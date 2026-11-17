"""Archivos Excel que genera la app: pago masivo al banco y listado de proveedores."""
import io
from typing import List, Optional

from openpyxl import Workbook
from openpyxl.styles import Font

from . import credito
from .modelos import FACTURA_PENDIENTE, Factura, Proveedor

# Mismos encabezados y mismo orden que la hoja de pago masivo del Excel original.
ENCABEZADOS_PAGO = [
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
TIPO_PAGO = "PA"
FORMA_PAGO = "CTA"
PREFIJO_REFERENCIA = "PAGO FAC"
HOJA_PAGO = "Hoja 1"
# Columnas que siempre van como texto para no perder ceros a la izquierda.
COLUMNAS_TEXTO = {"TIPO CTA", "NUMERO CTA", "TIPO ID", "NUMERO ID", "NOMBRE BENEFICIARIO", "CODIGOS BANCOS", "correo",
                  "DIAS CREDITO", "NOMBRE"}


def motivo_bloqueo(f: Factura) -> Optional[str]:
    """Por qué una factura NO puede ir en el archivo de pago; None si puede."""
    p = f.proveedor
    if f.estado != FACTURA_PENDIENTE:
        return f"La factura está {f.estado_texto.lower()}."
    if not p.activo:
        return "El proveedor está desactivado."
    if not p.aprobado:
        return f"El proveedor no está revisado (estado: {p.estado_texto})."
    faltan = []
    if not p.numero_cuenta:
        faltan.append("número de cuenta")
    if p.tipo_cuenta is None:
        faltan.append("tipo de cuenta")
    if p.banco is None:
        faltan.append("banco")
    if not p.numero_id or p.tipo_id is None:
        faltan.append("identificación")
    if faltan:
        return "Al proveedor le falta: " + ", ".join(faltan) + "."
    return None


def referencia(f: Factura) -> str:
    return f"{PREFIJO_REFERENCIA} {f.numero} {f.proveedor.nombre}"


def _valor_contrapartida(contrapartida: str):
    texto = (contrapartida or "").strip()
    # En el Excel original es un número; se conserva como número salvo que tenga ceros a la izquierda.
    if texto.isdigit() and (texto == "0" or not texto.startswith("0")):
        return int(texto)
    return texto


def fila_pago(f: Factura, contrapartida: str) -> list:
    p = f.proveedor
    return [
        p.nombre,
        TIPO_PAGO,
        _valor_contrapartida(contrapartida),
        f.moneda,
        float(f.valor),
        FORMA_PAGO,
        p.tipo_cuenta.codigo,
        p.numero_cuenta,
        referencia(f),
        p.tipo_id.nombre,
        p.numero_id,
        p.nombre,
        p.banco.codigo,
        p.correo or "",
        credito.texto_excel(p.credito_tipo, p.credito_valor),
    ]


def libro_pago_masivo(facturas: List[Factura], contrapartida: str) -> Workbook:
    """Libro con el formato de pago masivo. Lanza ValueError si alguna factura está bloqueada."""
    for f in facturas:
        motivo = motivo_bloqueo(f)
        if motivo:
            raise ValueError(f"La factura {f.numero} no se puede exportar: {motivo}")
    libro = Workbook()
    hoja = libro.active
    hoja.title = HOJA_PAGO
    hoja.append(ENCABEZADOS_PAGO)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for f in facturas:
        hoja.append(fila_pago(f, contrapartida))
    for fila in hoja.iter_rows(min_row=2):
        for celda, encabezado in zip(fila, ENCABEZADOS_PAGO):
            if encabezado in COLUMNAS_TEXTO:
                celda.number_format = "@"
                if celda.value is not None:
                    celda.value = str(celda.value)
                    celda.data_type = "s"
            elif encabezado == "VALOR":
                celda.number_format = "0.00"
    _anchos(hoja, ENCABEZADOS_PAGO)
    return libro


ENCABEZADOS_PROVEEDORES = [
    "NOMBRE",
    "REGISTRADO",
    "TIPO ID",
    "NUMERO ID",
    "TIPO CTA",
    "NUMERO CTA",
    "BANCO",
    "CODIGO BANCO",
    "CORREO",
    "ESTADO REVISION",
    "ACTIVO",
    "NOTAS",
]


def libro_proveedores(proveedores: List[Proveedor], empresas=()) -> Workbook:
    """Listado de proveedores con una columna de crédito por empresa, después de CORREO."""
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Proveedores"
    posicion = ENCABEZADOS_PROVEEDORES.index("CORREO") + 1
    encabezados = (
        ENCABEZADOS_PROVEEDORES[:posicion]
        + [f"CREDITO {e.nombre}" for e in empresas]
        + ENCABEZADOS_PROVEEDORES[posicion:]
    )
    hoja.append(encabezados)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for p in proveedores:
        creditos = []
        for e in empresas:
            fila = p.credito_de(e.id)
            creditos.append(credito.texto_excel(fila.credito_tipo, fila.credito_valor) if fila is not None else "")
        hoja.append(
            [
                p.nombre,
                "OK" if p.registrado_banco else "",
                p.tipo_id.nombre if p.tipo_id else "",
                p.numero_id or "",
                p.tipo_cuenta.codigo if p.tipo_cuenta else "",
                p.numero_cuenta or "",
                p.banco.nombre if p.banco else "",
                p.banco.codigo if p.banco else "",
                p.correo or "",
                *creditos,
                p.estado_texto,
                "SI" if p.activo else "NO",
                p.notas or "",
            ]
        )
    for fila in hoja.iter_rows(min_row=2):
        for celda in fila:
            celda.number_format = "@"
            celda.value = "" if celda.value is None else str(celda.value)
            celda.data_type = "s"
    _anchos(hoja, encabezados)
    return libro


def _anchos(hoja, encabezados) -> None:
    from openpyxl.utils import get_column_letter

    for i, encabezado in enumerate(encabezados, start=1):
        largo = max([len(encabezado)] + [len(str(c.value or "")) for c in hoja[get_column_letter(i)][1:200]])
        hoja.column_dimensions[get_column_letter(i)].width = min(60, max(10, largo + 2))


def a_bytes(libro: Workbook) -> bytes:
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
