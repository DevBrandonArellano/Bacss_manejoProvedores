"""Catálogos: semilla de instituciones financieras y carga opcional desde el Excel.

Los códigos de institución financiera son oficiales: se guardan como texto con
el mismo valor que traen, sin renumerar ni rellenar con ceros.

La carga desde Excel lee ÚNICAMENTE la hoja de catálogos; nunca la hoja del
maestro de proveedores.
"""
import csv
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy import select

from . import servicios
from .modelos import Banco, TipoCuenta, TipoId
from .servicios import ErrorNegocio, normalizar

SEMILLA_BANCOS = Path(__file__).resolve().parent / "semilla" / "instituciones_financieras.csv"
HOJA_CATALOGOS = "Hoja2"
MARCA_SEMILLA = "semilla_bancos"


@dataclass
class ResumenCatalogos:
    bancos_agregados: int = 0
    bancos_existentes: int = 0
    tipos_id_agregados: int = 0
    tipos_cuenta_agregados: int = 0
    avisos: List[str] = field(default_factory=list)

    def lineas(self) -> List[str]:
        return [
            f"Instituciones financieras agregadas: {self.bancos_agregados}",
            f"Instituciones financieras que ya existían (sin cambios): {self.bancos_existentes}",
            f"Tipos de ID agregados: {self.tipos_id_agregados}",
            f"Tipos de cuenta agregados: {self.tipos_cuenta_agregados}",
        ]


def texto_codigo(valor) -> Optional[str]:
    """Código tal como aparece: 10 -> "10", 10.0 -> "10", " 0042 " -> "0042"."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).strip()
    return texto or None


def leer_semilla(ruta: Path = SEMILLA_BANCOS) -> List[Tuple[str, str]]:
    with open(ruta, encoding="utf-8", newline="") as archivo:
        return [
            (fila["codigo"].strip(), fila["nombre"].strip())
            for fila in csv.DictReader(archivo)
            if fila.get("codigo", "").strip() and fila.get("nombre", "").strip()
        ]


def agregar_bancos(db, pares, resumen: ResumenCatalogos) -> None:
    """Agrega las instituciones que falten. Nunca modifica ni borra las existentes."""
    existentes = db.scalars(select(Banco)).all()
    claves = {(b.codigo, b.nombre_norm) for b in existentes}
    codigo_de = {}
    for b in existentes:
        codigo_de.setdefault(b.nombre_norm, b.codigo)
    nombres_de = {}
    for b in existentes:
        nombres_de.setdefault(b.codigo, set()).add(b.nombre_norm)

    for codigo, nombre in pares:
        norm = normalizar(nombre)
        if (codigo, norm) in claves:
            resumen.bancos_existentes += 1
            continue
        if norm in codigo_de:
            resumen.avisos.append(
                f"«{nombre}» ya existe con el código {codigo_de[norm]} y el archivo trae el código {codigo}: "
                "no se cambió. Si corresponde, edítelo a mano."
            )
            continue
        if nombres_de.get(codigo):
            resumen.avisos.append(f"El código {codigo} lo comparte más de una institución; se agregó «{nombre}».")
        db.add(Banco(codigo=codigo, nombre=nombre, nombre_norm=norm, activo=True))
        claves.add((codigo, norm))
        codigo_de[norm] = codigo
        nombres_de.setdefault(codigo, set()).add(norm)
        resumen.bancos_agregados += 1


def sembrar_bancos(db, ruta: Path = SEMILLA_BANCOS) -> int:
    """Carga la semilla una sola vez (al crear la base). Reiniciar no duplica ni pisa cambios manuales."""
    if servicios.cfg_leer(db, MARCA_SEMILLA) == "cargada":
        return 0
    resumen = ResumenCatalogos()
    agregar_bancos(db, leer_semilla(ruta), resumen)
    servicios.cfg_guardar(db, MARCA_SEMILLA, "cargada")
    db.commit()
    return resumen.bancos_agregados


def preparar_bd(db) -> None:
    """Todo lo que debe existir al arrancar: tipos, administrador inicial e instituciones financieras."""
    servicios.sembrar(db)
    sembrar_bancos(db)


# ---------------------------------------------------------------- carga desde Excel


def _es_tipo_cuenta(codigo: str, nombre: str) -> bool:
    n = normalizar(nombre)
    return normalizar(codigo) in ("AHO", "CTE") or "AHORRO" in n or "CORRIENTE" in n


def leer_hoja_catalogos(ruta, hoja: str = HOJA_CATALOGOS):
    """Devuelve (bancos, tipos) leídos de la hoja de catálogos. No abre ninguna otra hoja."""
    import openpyxl

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    except Exception:
        raise ErrorNegocio("No se pudo abrir el archivo. Debe ser un Excel .xlsx.")
    try:
        if hoja not in libro.sheetnames:
            raise ErrorNegocio(f"El archivo no tiene una hoja llamada «{hoja}» con los catálogos.")
        filas = [list(f) for f in libro[hoja].iter_rows(values_only=True)]
    finally:
        libro.close()

    # Pares de columnas "Código Banco" + "Nombre del Banco"
    columnas = []
    fila_encabezado = None
    for i, fila in enumerate(filas[:15]):
        for j in range(len(fila) - 1):
            if normalizar(fila[j]) == "CODIGO BANCO" and normalizar(fila[j + 1]) == "NOMBRE DEL BANCO":
                columnas.append(j)
        if columnas:
            fila_encabezado = i
            break
    if fila_encabezado is None:
        raise ErrorNegocio("No se encontraron las columnas «Código Banco» y «Nombre del Banco» en la hoja.")

    bancos = []
    for j in columnas:
        for fila in filas[fila_encabezado + 1 :]:
            if j + 1 >= len(fila):
                continue
            codigo, nombre = texto_codigo(fila[j]), servicios.limpiar(fila[j + 1])
            if codigo and nombre:
                bancos.append((codigo, str(fila[j + 1]).strip()))

    # Tipos de ID y de cuenta: pares código + nombre en las dos primeras columnas
    tipos = []
    for fila in filas[1:40]:
        if len(fila) < 2:
            continue
        codigo, nombre = servicios.limpiar(fila[0]), servicios.limpiar(fila[1])
        if codigo and nombre and len(codigo) <= 5 and isinstance(fila[0], str) and isinstance(fila[1], str):
            tipos.append((codigo.upper(), nombre.upper()))
    return bancos, tipos


def cargar_desde_excel(db, ruta, hoja: str = HOJA_CATALOGOS) -> ResumenCatalogos:
    """Agrega al catálogo lo que falte según la hoja de catálogos del Excel. Reejecutable sin duplicar."""
    bancos, tipos = leer_hoja_catalogos(ruta, hoja)
    resumen = ResumenCatalogos()
    agregar_bancos(db, bancos, resumen)
    for codigo, nombre in tipos:
        modelo = TipoCuenta if _es_tipo_cuenta(codigo, nombre) else TipoId
        if db.scalars(select(modelo).where(modelo.codigo == codigo)).first() is None:
            db.add(modelo(codigo=codigo, nombre=nombre, activo=True))
            db.flush()
            if modelo is TipoCuenta:
                resumen.tipos_cuenta_agregados += 1
            else:
                resumen.tipos_id_agregados += 1
    db.commit()
    return resumen
