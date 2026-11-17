"""Importación de proveedores desde un Excel.

Lee las hojas que tengan las columnas TIPO ID, NUMERO ID, TIPO CTA, NUMERO CTA y BANCOS (se detectan por sus
encabezados; las demás hojas se ignoran). El nombre del proveedor es la primera columna.

Reglas:
- Cada proveedor se identifica por tipo + número de ID. Si ya existe en la base se deja como está (no se
  pisan cambios hechos a mano), así que el comando se puede volver a correr sin duplicar.
- Cada proveedor entra por el mismo camino que el alta manual (`servicios.crear_proveedor`): con su
  historial y las mismas validaciones. Queda PENDIENTE de aprobación, salvo los marcados «OK» en la columna
  REGISTRADO del Excel: esos ya estaban aprobados y se importan como APROBADOS (queda anotado en su historial).
- Lo que no se puede importar se omite y se explica por hoja y fila. El informe nunca incluye nombres,
  identificaciones ni cuentas: la fila se busca en el Excel.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select

from . import config, credito, servicios
from .catalogos import texto_codigo
from .modelos import APROBADO, Banco, Empresa, Proveedor, TipoCuenta, TipoId, Usuario
from .servicios import ErrorNegocio, limpiar, normalizar, partes_correo, sin_espacios

OBLIGATORIAS = {"TIPO ID", "NUMERO ID", "TIPO CTA", "NUMERO CTA", "BANCOS"}
SINONIMOS_CUENTA = {"CORRIENTE": "CTE", "AHORROS": "AHO", "AHORRO": "AHO"}


@dataclass
class Resumen:
    hojas: List[str] = field(default_factory=list)
    filas_con_datos: int = 0
    importados: int = 0
    aprobados: int = 0  # de los importados, los que venían marcados OK
    ya_existian: int = 0
    repetidos: int = 0
    omitidos: List[Tuple[str, int, str]] = field(default_factory=list)  # (hoja, fila, motivo)
    avisos: List[Tuple[str, int, str]] = field(default_factory=list)  # importado, pero con algo que revisar
    creditos: int = 0  # créditos guardados para la empresa indicada
    con_empresa: bool = False

    def lineas(self) -> List[str]:
        creditos = (
            f"Créditos importados: {self.creditos}"
            if self.con_empresa
            else "Créditos del Excel: no importados (indique --empresa)"
        )
        return [
            f"Hojas leídas: {', '.join(self.hojas) or '(ninguna)'}",
            f"Filas con datos de proveedor: {self.filas_con_datos}",
            f"Importados: {self.importados}",
            f"  - ya revisados (REGISTRADO = OK en el Excel): {self.aprobados}",
            f"  - pendientes de revisión: {self.importados - self.aprobados}",
            f"Ya existían en la base (sin cambios): {self.ya_existian}",
            f"Repetidos en el propio Excel con los mismos datos: {self.repetidos}",
            f"Omitidos: {len(self.omitidos)}",
            f"Importados con algo que revisar: {len(self.avisos)}",
            creditos,
        ]


# ---------------------------------------------------------------- lectura del Excel


def _encabezado(valor) -> str:
    return normalizar(valor)


def _texto_celda(valor) -> Optional[str]:
    """Texto de una celda; descarta errores y fórmulas sin valor (#N/A, #REF!, =BUSCARV(...))."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = limpiar(valor)
    if texto is None or texto[0] in "#=":
        return None
    return texto


def _columnas(fila_encabezados) -> Optional[Dict[str, int]]:
    posiciones = {}
    for i, valor in enumerate(fila_encabezados):
        nombre = _encabezado(valor)
        if nombre and nombre not in posiciones:
            posiciones[nombre] = i
    if not OBLIGATORIAS <= set(posiciones):
        return None
    cols = {
        "id_tipo": posiciones["TIPO ID"],
        "id_numero": posiciones["NUMERO ID"],
        "cta_tipo": posiciones["TIPO CTA"],
        "cta_numero": posiciones["NUMERO CTA"],
        "banco": posiciones["BANCOS"],
        "nombre": 0,
    }
    for clave, nombre in (("credito", "DIAS CREDITO"), ("registrado", "REGISTRADO"), ("correo", "CORREO")):
        if nombre in posiciones:
            cols[clave] = posiciones[nombre]
    # El código del banco suele estar en la columna siguiente, sin encabezado (respaldo si el nombre no coincide).
    if not _encabezado(fila_encabezados[cols["banco"] + 1] if len(fila_encabezados) > cols["banco"] + 1 else None):
        cols["banco_codigo"] = cols["banco"] + 1
    return cols


def leer_hojas(ruta) -> List[Tuple[str, Dict[str, int], list]]:
    """[(nombre de la hoja, columnas, filas)] solo de las hojas de proveedores."""
    import openpyxl
    import warnings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    except FileNotFoundError:
        raise
    except Exception:
        raise ErrorNegocio("No se pudo abrir el archivo. Debe ser un Excel .xlsx.")
    try:
        hojas = []
        for hoja in libro.worksheets:
            filas = list(hoja.iter_rows(values_only=True))
            cols = _columnas(filas[0]) if filas else None
            if cols is not None:
                hojas.append((hoja.title, cols, filas))
        return hojas
    finally:
        libro.close()


# ---------------------------------------------------------------- interpretación de cada fila


class _Catalogos:
    def __init__(self, db):
        self.tipos_id = {}
        for t in db.scalars(select(TipoId)).all():
            self.tipos_id[normalizar(t.nombre)] = t
            self.tipos_id[normalizar(t.codigo)] = t
        self.tipos_cuenta = {}
        for t in db.scalars(select(TipoCuenta)).all():
            self.tipos_cuenta[normalizar(t.nombre)] = t
            self.tipos_cuenta[normalizar(t.codigo)] = t
        self.bancos_por_nombre: Dict[str, List[Banco]] = {}
        self.bancos_por_codigo: Dict[str, List[Banco]] = {}
        for b in db.scalars(select(Banco).where(Banco.activo.is_(True))).all():
            self.bancos_por_nombre.setdefault(b.nombre_norm, []).append(b)
            self.bancos_por_codigo.setdefault(b.codigo, []).append(b)

    def banco(self, nombre: Optional[str], codigo: Optional[str]) -> Optional[Banco]:
        if nombre:
            coincidencias = self.bancos_por_nombre.get(normalizar(nombre), [])
            if len(coincidencias) == 1:
                return coincidencias[0]
            if len(coincidencias) > 1 and codigo:
                con_codigo = [b for b in coincidencias if b.codigo == codigo]
                if len(con_codigo) == 1:
                    return con_codigo[0]
        if codigo:
            por_codigo = self.bancos_por_codigo.get(codigo, [])
            if len(por_codigo) == 1:
                return por_codigo[0]
        return None


def _celda(fila, cols, clave):
    i = cols.get(clave)
    return fila[i] if i is not None and i < len(fila) else None


def _numero(valor) -> Optional[str]:
    """ID o cuenta como texto, sin espacios y sin '.0' si Excel lo guardó como número."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = sin_espacios(valor)
    return None if texto is None or texto[0] in "#=" else texto


def _notas_extra(fila, cols) -> Optional[str]:
    """Texto suelto en columnas sin encabezado a la derecha del correo (p. ej. una categoría)."""
    ultima = max(cols.get("correo", -1), cols["banco"] + 1)
    textos = []
    for valor in fila[ultima + 1 :]:
        texto = _texto_celda(valor)
        if texto:
            textos.append(texto)
    return ("Nota del Excel: " + "; ".join(textos)) if textos else None


def _aprobar_por_excel(db, p: Proveedor, usuario: Usuario) -> None:
    """El Excel ya lo da por aprobado (REGISTRADO = OK): se refleja el estado y se deja constancia en el historial."""
    p.estado_aprobacion = APROBADO
    p.aprobado_por_id = None  # la aprobación ocurrió antes de la app: no se atribuye a nadie
    p.aprobado_en = config.ahora()
    p.motivo_rechazo = None
    servicios._registrar(
        db, p, usuario, "aprobacion", "Estado de revisión", "Pendiente", "Revisado (según el Excel: REGISTRADO = OK)"
    )


def _firma(datos: dict) -> tuple:
    return (datos["tipo_cuenta_id"], datos["numero_cuenta"], datos["banco_id"])


# ---------------------------------------------------------------- importación


def importar(db, ruta, usuario: Usuario, empresa: Optional[Empresa] = None) -> Resumen:
    """Crea los proveedores del Excel. No hace commit: quien llama decide (guardar o descartar).

    El crédito del Excel es de una empresa: solo se guarda si se indica `empresa`. Los proveedores que ya
    existían no se tocan (tampoco su crédito).
    """
    resumen = Resumen(con_empresa=empresa is not None)
    hojas = leer_hojas(ruta)
    if not hojas:
        raise ErrorNegocio(
            "No se encontró ninguna hoja de proveedores (se buscan las columnas TIPO ID, NUMERO ID, TIPO CTA, "
            "NUMERO CTA y BANCOS)."
        )
    cat = _Catalogos(db)
    existentes = {
        (p.tipo_id_id, p.numero_id) for p in db.scalars(select(Proveedor).where(Proveedor.numero_id.is_not(None))).all()
    }
    vistos: Dict[tuple, Tuple[str, int, tuple, Proveedor]] = {}  # (tipo, número) -> (hoja, fila, firma, proveedor)

    for nombre_hoja, cols, filas in hojas:
        resumen.hojas.append(nombre_hoja)
        for n, fila in enumerate(filas[1:], start=2):
            nombre = _texto_celda(_celda(fila, cols, "nombre"))
            texto_tipo = _texto_celda(_celda(fila, cols, "id_tipo"))
            numero_id = _numero(_celda(fila, cols, "id_numero"))
            numero_cta = _numero(_celda(fila, cols, "cta_numero"))
            # Sin nombre ni número de ID no es un proveedor (filas vacías o relleno de fórmulas).
            if not nombre and not numero_id:
                continue
            resumen.filas_con_datos += 1

            def omitir(motivo: str) -> None:
                resumen.omitidos.append((nombre_hoja, n, motivo))

            if not nombre:
                omitir("Sin nombre.")
                continue
            if not numero_id:
                omitir("Sin número de identificación.")
                continue
            tipo_id = cat.tipos_id.get(normalizar(texto_tipo)) if texto_tipo else None
            if tipo_id is None:
                omitir("Tipo de ID vacío o no reconocido.")
                continue

            texto_cta = _texto_celda(_celda(fila, cols, "cta_tipo"))
            tipo_cta = None
            if texto_cta:
                clave = normalizar(texto_cta)
                tipo_cta = cat.tipos_cuenta.get(SINONIMOS_CUENTA.get(clave, clave))
                if tipo_cta is None:
                    omitir("Tipo de cuenta no reconocido.")
                    continue

            revisar = []
            banco_texto = _texto_celda(_celda(fila, cols, "banco"))
            banco = cat.banco(banco_texto, texto_codigo(_celda(fila, cols, "banco_codigo")) if "banco_codigo" in cols else None)
            if banco is None and (banco_texto or numero_cta):
                revisar.append("Banco no reconocido en el catálogo: quedó sin banco.")

            tipo_cred, valor_cred = None, None
            texto_cred = _texto_celda(_celda(fila, cols, "credito"))
            if texto_cred:
                tipo_cred, valor_cred = credito.interpretar(texto_cred)
                if tipo_cred is None:
                    revisar.append("Condición de crédito no reconocida: quedó sin definir.")

            notas = [_notas_extra(fila, cols)]
            correo = None
            texto_correo = _texto_celda(_celda(fila, cols, "correo"))
            if texto_correo:
                partes = partes_correo(texto_correo.replace("\n", ";").replace(" ", ";"))
                if partes and servicios.correo_valido("; ".join(partes)):
                    correo = "; ".join(partes)
                else:
                    revisar.append("Correo con formato no válido: no se importó (queda en las notas).")
                    notas.append(f"Correo original (no válido): {texto_correo}")

            datos = {
                "nombre": nombre,
                "tipo_id_id": tipo_id.id,
                "numero_id": numero_id,
                "tipo_cuenta_id": tipo_cta.id if tipo_cta else None,
                "numero_cuenta": numero_cta,
                "banco_id": banco.id if banco else None,
                "correo": correo,
                "registrado_banco": normalizar(_texto_celda(_celda(fila, cols, "registrado"))) == "OK",
                "notas": "\n".join(t for t in notas if t) or None,
            }
            clave_prov = (tipo_id.id, numero_id)
            if clave_prov in existentes:
                resumen.ya_existian += 1
                continue
            if clave_prov in vistos:
                hoja0, fila0, firma0, creado = vistos[clave_prov]
                if firma0 == _firma(datos):
                    resumen.repetidos += 1
                    if datos["registrado_banco"] and creado.estado_aprobacion != APROBADO:
                        _aprobar_por_excel(db, creado, usuario)  # la otra hoja sí lo trae como OK
                        resumen.aprobados += 1
                else:
                    omitir(
                        f"Mismo ID que la hoja {hoja0}, fila {fila0}, pero con otra cuenta o banco: revisar a mano."
                    )
                continue

            errores = servicios.validar_datos(db, datos)
            error_credito = credito.validar(tipo_cred, valor_cred)  # p. ej. 400 días: se omite, como antes
            if error_credito:
                errores.append(error_credito)
            if errores:
                omitir(" ".join(errores))
                continue
            p = servicios.crear_proveedor(db, datos, usuario)
            if empresa is not None and tipo_cred:
                if servicios.aplicar_credito(db, p, empresa, tipo_cred, valor_cred, usuario):
                    resumen.creditos += 1
            vistos[clave_prov] = (nombre_hoja, n, _firma(datos), p)
            resumen.importados += 1
            if datos["registrado_banco"]:
                _aprobar_por_excel(db, p, usuario)
                resumen.aprobados += 1
            for texto in revisar:
                resumen.avisos.append((nombre_hoja, n, texto))
    return resumen
