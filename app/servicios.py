"""Reglas de negocio: proveedores, aprobación, facturas, usuarios y configuración."""
import logging
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from sqlalchemy import func, select

from . import config, credito, identificacion, seguridad
from .modelos import (
    ADMINISTRADOR,
    APROBADO,
    FACTURA_ANULADA,
    FACTURA_PAGADA,
    FACTURA_PENDIENTE,
    PENDIENTE,
    RECHAZADO,
    ROLES,
    Banco,
    Configuracion,
    Factura,
    Historial,
    Proveedor,
    TipoCuenta,
    TipoId,
    Usuario,
)

registro = logging.getLogger(__name__)

class ErrorNegocio(Exception):
    """Operación no permitida; el mensaje se muestra al usuario."""


# ---------------------------------------------------------------- texto

CORREO_RE = re.compile(r"^[^@\s;,]+@[^@\s;,]+\.[^@\s;,.]+$")


def normalizar(texto) -> str:
    """Mayúsculas, sin acentos y con espacios simples; sirve para comparar y buscar."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().upper()


def limpiar(valor) -> Optional[str]:
    """Quita espacios sobrantes; None si queda vacío."""
    if valor is None:
        return None
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    return texto or None


def sin_espacios(valor) -> Optional[str]:
    """Para números de ID y de cuenta: siempre texto, sin espacios, conserva los ceros."""
    if valor is None:
        return None
    texto = re.sub(r"\s+", "", str(valor))
    return texto or None


def partes_correo(texto) -> List[str]:
    return [p.strip() for p in re.split(r"[;,]", texto or "") if p.strip()]


def correo_valido(texto) -> bool:
    partes = partes_correo(texto)
    return bool(partes) and all(CORREO_RE.match(p) for p in partes)


# ---------------------------------------------------------------- configuración

DIAS_AVISO_DEFECTO = 7
CONTRAPARTIDA_DEFECTO = "1"


def cfg_leer(db, clave: str, defecto: str = "") -> str:
    fila = db.get(Configuracion, clave)
    return fila.valor if fila is not None else defecto


def cfg_guardar(db, clave: str, valor) -> None:
    fila = db.get(Configuracion, clave)
    if fila is None:
        db.add(Configuracion(clave=clave, valor=str(valor)))
    else:
        fila.valor = str(valor)


def dias_aviso(db) -> int:
    try:
        return max(0, int(cfg_leer(db, "dias_aviso", str(DIAS_AVISO_DEFECTO))))
    except ValueError:
        return DIAS_AVISO_DEFECTO


def contrapartida(db) -> str:
    return cfg_leer(db, "contrapartida", CONTRAPARTIDA_DEFECTO)


# ---------------------------------------------------------------- catálogos y usuarios

TIPOS_ID_INICIALES = [("C", "CEDULA"), ("R", "RUC"), ("P", "PASAPORTE")]
TIPOS_CUENTA_INICIALES = [("AHO", "AHORROS"), ("CTE", "CORRIENTE")]


def sembrar(db) -> None:
    """Deja listos los catálogos fijos y el administrador inicial. Se puede repetir."""
    for modelo, iniciales in ((TipoId, TIPOS_ID_INICIALES), (TipoCuenta, TIPOS_CUENTA_INICIALES)):
        if db.scalar(select(func.count()).select_from(modelo)) == 0:
            for codigo, nombre in iniciales:
                db.add(modelo(codigo=codigo, nombre=nombre, activo=True))
    cfg = config.actual
    if cfg.admin_clave == "cambie-esta-clave":
        registro.warning("ADMIN_CLAVE conserva el valor de ejemplo; no se crea el administrador inicial.")
    elif db.scalar(select(func.count()).select_from(Usuario)) == 0 and cfg.admin_usuario and cfg.admin_clave:
        db.add(
            Usuario(
                usuario=cfg.admin_usuario,
                nombre=cfg.admin_nombre,
                clave_hash=seguridad.cifrar(cfg.admin_clave),
                rol=ADMINISTRADOR,
                activo=True,
                creado_en=config.ahora(),
            )
        )
    db.commit()


def crear_usuario(db, usuario: str, nombre: str, clave: str, rol: str) -> Usuario:
    usuario = (usuario or "").strip().lower()
    nombre = limpiar(nombre) or ""
    if not re.fullmatch(r"[a-z0-9._-]{3,60}", usuario):
        raise ErrorNegocio("El usuario debe tener de 3 a 60 caracteres: letras, números, punto, guion.")
    if not nombre:
        raise ErrorNegocio("Escriba el nombre de la persona.")
    if rol not in ROLES:
        raise ErrorNegocio("Perfil desconocido.")
    error = seguridad.error_clave(clave)
    if error:
        raise ErrorNegocio(error)
    if db.scalar(select(Usuario).where(Usuario.usuario == usuario)) is not None:
        raise ErrorNegocio("Ya existe un usuario con ese nombre de usuario.")
    nuevo = Usuario(
        usuario=usuario,
        nombre=nombre,
        clave_hash=seguridad.cifrar(clave),
        rol=rol,
        activo=True,
        creado_en=config.ahora(),
    )
    db.add(nuevo)
    db.flush()
    return nuevo


def admins_activos(db, excluir_id: int = None) -> int:
    consulta = select(func.count()).select_from(Usuario).where(Usuario.rol == ADMINISTRADOR, Usuario.activo.is_(True))
    if excluir_id is not None:
        consulta = consulta.where(Usuario.id != excluir_id)
    return db.scalar(consulta) or 0


def actualizar_usuario(db, u: Usuario, nombre: str, rol: str, activo: bool, clave: str = "") -> None:
    nombre = limpiar(nombre) or ""
    if not nombre:
        raise ErrorNegocio("Escriba el nombre de la persona.")
    if rol not in ROLES:
        raise ErrorNegocio("Perfil desconocido.")
    deja_de_ser_admin = u.rol == ADMINISTRADOR and u.activo and (rol != ADMINISTRADOR or not activo)
    if deja_de_ser_admin and admins_activos(db, excluir_id=u.id) == 0:
        raise ErrorNegocio("Debe quedar al menos un administrador activo.")
    if clave:
        error = seguridad.error_clave(clave)
        if error:
            raise ErrorNegocio(error)
        u.clave_hash = seguridad.cifrar(clave)
    u.nombre = nombre
    u.rol = rol
    u.activo = activo


# ---------------------------------------------------------------- proveedores

CAMPOS = [
    "nombre",
    "tipo_id_id",
    "numero_id",
    "tipo_cuenta_id",
    "numero_cuenta",
    "banco_id",
    "correo",
    "registrado_banco",
    "notas",
    "activo",
]
# Un cambio en cualquiera de estos devuelve al proveedor a "Pendiente de aprobación".
SENSIBLES = {"nombre", "tipo_id_id", "numero_id", "tipo_cuenta_id", "numero_cuenta", "banco_id"}
ETIQUETAS = {
    "nombre": "Nombre",
    "tipo_id_id": "Tipo de ID",
    "numero_id": "Número de ID",
    "tipo_cuenta_id": "Tipo de cuenta",
    "numero_cuenta": "Número de cuenta",
    "banco_id": "Banco",
    "correo": "Correo",
    "registrado_banco": "Registrado en el banco",
    "notas": "Notas",
    "activo": "Activo",
    "credito": "Condición de crédito",
}
LARGO_ID = {"C": 10, "R": 13}  # cédula y RUC de Ecuador


def _mostrar(db, campo: str, valor) -> str:
    if valor is None or valor == "":
        return "(vacío)"
    if campo == "tipo_id_id":
        fila = db.get(TipoId, valor)
        return fila.nombre if fila else str(valor)
    if campo == "tipo_cuenta_id":
        fila = db.get(TipoCuenta, valor)
        return fila.nombre if fila else str(valor)
    if campo == "banco_id":
        fila = db.get(Banco, valor)
        return f"{fila.nombre} (código {fila.codigo})" if fila else str(valor)
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    return str(valor)


def _registrar(db, p: Proveedor, usuario: Usuario, tipo: str, campo: str, anterior, nuevo, sensible=False) -> None:
    db.add(
        Historial(
            proveedor_id=p.id,
            tipo=tipo,
            campo=campo,
            valor_anterior=anterior,
            valor_nuevo=nuevo,
            sensible=sensible,
            usuario_id=usuario.id,
            usuario_nombre=f"{usuario.nombre} ({usuario.usuario})",
            fecha=config.ahora(),
        )
    )


def validar_datos(db, datos: dict, proveedor_id: int = None) -> List[str]:
    """Errores que impiden guardar un proveedor."""
    errores = []
    if not datos.get("nombre"):
        errores.append("El nombre es obligatorio.")
    numero_id = datos.get("numero_id")
    tipo = db.get(TipoId, datos["tipo_id_id"]) if datos.get("tipo_id_id") else None
    if datos.get("tipo_id_id") and tipo is None:
        errores.append("El tipo de ID elegido no existe.")
    elif numero_id and tipo is None:
        errores.append("Elija el tipo de ID.")
    if datos.get("tipo_cuenta_id") and db.get(TipoCuenta, datos["tipo_cuenta_id"]) is None:
        errores.append("El tipo de cuenta elegido no existe.")
    if datos.get("banco_id") and db.get(Banco, datos["banco_id"]) is None:
        errores.append("El banco elegido no existe en el catálogo.")
    if numero_id and tipo is not None:
        largo = LARGO_ID.get(tipo.codigo)
        if largo and not (numero_id.isdigit() and len(numero_id) == largo):
            errores.append(f"Un número de {tipo.nombre} debe tener {largo} dígitos.")
        elif largo:
            errores.extend(identificacion.revisar(tipo.codigo, numero_id).errores)
        consulta = select(Proveedor).where(Proveedor.tipo_id_id == tipo.id, Proveedor.numero_id == numero_id)
        if proveedor_id is not None:
            consulta = consulta.where(Proveedor.id != proveedor_id)
        if db.scalars(consulta).first() is not None:
            errores.append("Ya existe un proveedor con ese tipo y número de ID.")
    if datos.get("numero_cuenta") and not datos.get("tipo_cuenta_id"):
        errores.append("Elija el tipo de cuenta.")
    if datos.get("correo") and not correo_valido(datos["correo"]):
        errores.append("El correo no tiene un formato válido (varios correos se separan con punto y coma).")
    error_credito = credito.validar(datos.get("credito_tipo"), datos.get("credito_valor"))
    if error_credito:
        errores.append(error_credito)
    return errores


def crear_proveedor(db, datos: dict, usuario: Usuario) -> Proveedor:
    """Da de alta un proveedor. Siempre nace Pendiente de aprobación."""
    ahora = config.ahora()
    p = Proveedor(
        nombre=datos["nombre"],
        nombre_norm=normalizar(datos["nombre"]),
        tipo_id_id=datos.get("tipo_id_id"),
        numero_id=datos.get("numero_id"),
        tipo_cuenta_id=datos.get("tipo_cuenta_id"),
        numero_cuenta=datos.get("numero_cuenta"),
        banco_id=datos.get("banco_id"),
        correo=datos.get("correo"),
        credito_tipo=datos.get("credito_tipo"),
        credito_valor=datos.get("credito_valor"),
        registrado_banco=bool(datos.get("registrado_banco")),
        notas=datos.get("notas"),
        activo=True,
        estado_aprobacion=PENDIENTE,
        creado_por_id=usuario.id,
        creado_en=ahora,
        modificado_por_id=usuario.id,
        modificado_en=ahora,
    )
    db.add(p)
    db.flush()
    _registrar(db, p, usuario, "creacion", "Proveedor", None, "Creado")
    return p


def aplicar_cambios(db, p: Proveedor, datos: dict, usuario: Usuario) -> List[str]:
    """Guarda los cambios, los anota en el historial y devuelve los campos cambiados.

    Si cambia un dato bancario o de identificación de un proveedor aprobado,
    vuelve a quedar Pendiente de aprobación.
    """
    cambios = []
    for campo in CAMPOS:
        if campo not in datos:
            continue
        anterior, nuevo = getattr(p, campo), datos[campo]
        if anterior == nuevo:
            continue
        cambios.append((campo, _mostrar(db, campo, anterior), _mostrar(db, campo, nuevo)))
        setattr(p, campo, nuevo)
    if "credito_tipo" in datos:
        antes = (p.credito_tipo, p.credito_valor)
        despues = (datos.get("credito_tipo"), datos.get("credito_valor"))
        if antes != despues:
            cambios.append(("credito", credito.texto(*antes), credito.texto(*despues)))
            p.credito_tipo, p.credito_valor = despues
    if not cambios:
        return []

    p.nombre_norm = normalizar(p.nombre)
    for campo, anterior, nuevo in cambios:
        _registrar(db, p, usuario, "cambio", ETIQUETAS[campo], anterior, nuevo, sensible=campo in SENSIBLES)
    p.modificado_por_id = usuario.id
    p.modificado_en = config.ahora()

    nombres = [c[0] for c in cambios]
    cambio_sensible = any(c in SENSIBLES for c in nombres)
    reenvio = p.estado_aprobacion == RECHAZADO and any(c != "activo" for c in nombres)
    if (p.estado_aprobacion == APROBADO and cambio_sensible) or reenvio:
        _registrar(db, p, usuario, "estado", "Estado de aprobación", p.estado_texto, "Pendiente")
        p.estado_aprobacion = PENDIENTE
        p.aprobado_por_id = None
        p.aprobado_en = None
        p.motivo_rechazo = None
    return nombres


def motivo_no_puede_aprobar(p: Proveedor, usuario: Usuario) -> Optional[str]:
    """None si `usuario` puede aprobar o rechazar a `p`; si no, el motivo."""
    if not usuario.puede_aprobar:
        return "Su perfil no permite aprobar proveedores."
    if p.estado_aprobacion != PENDIENTE:
        return "El proveedor no está pendiente de aprobación."
    if usuario.id == p.creado_por_id:
        return "No puede aprobar un proveedor que usted mismo creó."
    if usuario.id == p.modificado_por_id:
        return "No puede aprobar un proveedor cuya última modificación hizo usted."
    return None


def aprobar(db, p: Proveedor, usuario: Usuario) -> None:
    motivo = motivo_no_puede_aprobar(p, usuario)
    if motivo:
        raise ErrorNegocio(motivo)
    p.estado_aprobacion = APROBADO
    p.aprobado_por_id = usuario.id
    p.aprobado_en = config.ahora()
    p.motivo_rechazo = None
    _registrar(db, p, usuario, "aprobacion", "Estado de aprobación", "Pendiente", "Aprobado")


def rechazar(db, p: Proveedor, usuario: Usuario, motivo_rechazo: str) -> None:
    motivo = motivo_no_puede_aprobar(p, usuario)
    if motivo:
        raise ErrorNegocio(motivo)
    motivo_rechazo = limpiar(motivo_rechazo)
    if not motivo_rechazo:
        raise ErrorNegocio("Para rechazar debe escribir el motivo.")
    p.estado_aprobacion = RECHAZADO
    p.aprobado_por_id = usuario.id
    p.aprobado_en = config.ahora()
    p.motivo_rechazo = motivo_rechazo
    _registrar(db, p, usuario, "rechazo", "Estado de aprobación", "Pendiente", f"Rechazado: {motivo_rechazo}")


def cambios_por_revisar(db, p: Proveedor) -> List[Historial]:
    """Movimientos del historial desde la última aprobación o rechazo (lo que el aprobador debe mirar)."""
    filas = db.scalars(
        select(Historial).where(Historial.proveedor_id == p.id).order_by(Historial.fecha.desc(), Historial.id.desc())
    ).all()
    recientes = []
    for fila in filas:
        if fila.tipo in ("aprobacion", "rechazo"):
            break
        if fila.tipo in ("creacion", "cambio"):
            recientes.append(fila)
    recientes.reverse()
    return recientes


def contar_pendientes(db) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Proveedor)
            .where(Proveedor.estado_aprobacion == PENDIENTE, Proveedor.activo.is_(True))
        )
        or 0
    )


# ---------------------------------------------------------------- facturas


def interpretar_valor(texto) -> int:
    """Convierte "1234.56" o "1.234,56" en centavos. Lanza ErrorNegocio si no es un valor mayor que cero."""
    t = re.sub(r"\s+", "", str(texto or ""))
    if "," in t and "." in t:
        # el último separador es el decimal
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        valor = Decimal(t)
    except (InvalidOperation, ValueError):
        raise ErrorNegocio("El valor de la factura no es un número válido.")
    if not valor.is_finite() or valor <= 0:
        raise ErrorNegocio("El valor de la factura debe ser mayor que cero.")
    if valor > Decimal("999999999.99"):
        raise ErrorNegocio("El valor de la factura es demasiado grande.")
    if valor != valor.quantize(Decimal("0.01")):
        raise ErrorNegocio("El valor admite como máximo dos decimales.")
    return int(valor * 100)


def crear_factura(
    db, p: Proveedor, numero: str, fecha: date, valor_centavos: int, moneda: str, usuario: Usuario, notas: str = None
) -> Factura:
    numero = limpiar(numero)
    if not numero:
        raise ErrorNegocio("El número de factura es obligatorio.")
    if not p.activo:
        raise ErrorNegocio("El proveedor está desactivado; no se le pueden registrar facturas.")
    moneda = (moneda or "USD").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", moneda):
        raise ErrorNegocio("La moneda debe ser un código de tres letras, por ejemplo USD.")
    repetida = db.scalars(
        select(Factura).where(
            Factura.proveedor_id == p.id, Factura.numero == numero, Factura.estado != FACTURA_ANULADA
        )
    ).first()
    if repetida is not None:
        raise ErrorNegocio("Ese proveedor ya tiene registrada una factura con ese número.")
    f = Factura(
        proveedor_id=p.id,
        numero=numero,
        fecha=fecha,
        valor_centavos=valor_centavos,
        moneda=moneda,
        vencimiento=credito.calcular_vencimiento(fecha, p.credito_tipo, p.credito_valor),
        estado=FACTURA_PENDIENTE,
        notas=limpiar(notas),
        creado_por_id=usuario.id,
        creado_en=config.ahora(),
    )
    db.add(f)
    db.flush()
    return f


def marcar_pagada(db, f: Factura, usuario: Usuario, fecha: date = None) -> None:
    if f.estado != FACTURA_PENDIENTE:
        raise ErrorNegocio("Solo se puede marcar como pagada una factura pendiente.")
    f.estado = FACTURA_PAGADA
    f.pagada_en = fecha or config.hoy()
    f.pagada_por_id = usuario.id


def reabrir_factura(db, f: Factura) -> None:
    if f.estado == FACTURA_PENDIENTE:
        raise ErrorNegocio("La factura ya está pendiente.")
    repetida = db.scalars(
        select(Factura).where(
            Factura.proveedor_id == f.proveedor_id,
            Factura.numero == f.numero,
            Factura.estado != FACTURA_ANULADA,
            Factura.id != f.id,
        )
    ).first()
    if repetida is not None:
        raise ErrorNegocio("No se puede reabrir: el proveedor ya tiene otra factura con ese número.")
    f.estado = FACTURA_PENDIENTE
    f.pagada_en = None
    f.pagada_por_id = None


def anular_factura(db, f: Factura) -> None:
    if f.estado != FACTURA_PENDIENTE:
        raise ErrorNegocio("Solo se puede anular una factura pendiente.")
    f.estado = FACTURA_ANULADA


def facturas_por_vencer(db, hoy: date, dias: int) -> dict:
    """Facturas pendientes agrupadas para el panel: vencidas, de hoy y de los próximos `dias` días."""
    from datetime import timedelta

    limite = hoy + timedelta(days=dias)
    filas = db.scalars(
        select(Factura)
        .where(Factura.estado == FACTURA_PENDIENTE, Factura.vencimiento <= limite)
        .order_by(Factura.vencimiento, Factura.id)
    ).all()
    return {
        "vencidas": [f for f in filas if f.vencimiento < hoy],
        "hoy": [f for f in filas if f.vencimiento == hoy],
        "proximas": [f for f in filas if f.vencimiento > hoy],
    }


def totales(facturas) -> str:
    """Suma por moneda, por ejemplo "USD 1,250.00"."""
    sumas = {}
    for f in facturas:
        sumas[f.moneda] = sumas.get(f.moneda, 0) + f.valor_centavos
    return " · ".join(f"{moneda} {centavos / 100:,.2f}" for moneda, centavos in sorted(sumas.items()))
