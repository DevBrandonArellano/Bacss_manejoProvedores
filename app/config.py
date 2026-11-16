"""Configuración leída de variables de entorno (archivo .env)."""
import os
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent


def _texto(nombre: str, defecto: str = "") -> str:
    return (os.getenv(nombre) or defecto).strip()


def _bool(nombre: str, defecto: bool = False) -> bool:
    valor = _texto(nombre)
    if not valor:
        return defecto
    return valor.lower() in ("1", "true", "si", "sí", "yes", "on", "verdadero")


def _entero(nombre: str, defecto: int) -> int:
    try:
        return int(_texto(nombre) or defecto)
    except ValueError:
        return defecto


def _ruta(nombre: str, defecto: str) -> Path:
    ruta = Path(_texto(nombre, defecto))
    return ruta if ruta.is_absolute() else RAIZ / ruta


@dataclass
class Config:
    ruta_bd: Path
    ruta_respaldos: Path
    ruta_excel: Path
    respaldos_conservar: int
    clave_sesion: str
    clave_sesion_generada: bool
    cookie_segura: bool
    admin_usuario: str
    admin_clave: str
    admin_nombre: str
    zona: str
    hora_tarea: str
    tareas_activas: bool
    facturacion_activa: bool
    correo_activo: bool
    smtp_host: str
    smtp_puerto: int
    smtp_usuario: str
    smtp_clave: str
    smtp_tls: bool
    correo_remitente: str
    correo_destinatarios: list = field(default_factory=list)


def cargar() -> Config:
    """Lee la configuración del entorno. Se vuelve a llamar al crear la app."""
    global actual
    load_dotenv(RAIZ / ".env")
    clave = _texto("CLAVE_SESION")
    generada = False
    if len(clave) < 16:
        # Sin clave fija las sesiones se pierden en cada reinicio; se avisa al arrancar.
        clave = secrets.token_urlsafe(48)
        generada = True
    destinatarios = [c.strip() for c in _texto("CORREO_DESTINATARIOS").replace(";", ",").split(",") if c.strip()]
    actual = Config(
        ruta_bd=_ruta("RUTA_BD", "bd/proveedores.db"),
        ruta_respaldos=_ruta("RUTA_RESPALDOS", "respaldos"),
        ruta_excel=_ruta("RUTA_EXCEL", "datos/proveedores.xlsx"),
        respaldos_conservar=max(1, _entero("RESPALDOS_CONSERVAR", 30)),
        clave_sesion=clave,
        clave_sesion_generada=generada,
        cookie_segura=_bool("COOKIE_SEGURA", False),
        admin_usuario=_texto("ADMIN_USUARIO").lower(),
        admin_clave=os.getenv("ADMIN_CLAVE") or "",
        admin_nombre=_texto("ADMIN_NOMBRE", "Administrador"),
        zona=_texto("ZONA_HORARIA", "America/Guayaquil"),
        hora_tarea=_texto("HORA_TAREA_DIARIA", "07:00"),
        tareas_activas=_bool("TAREAS_ACTIVAS", True),
        facturacion_activa=_bool("FACTURACION_ACTIVA", False),
        correo_activo=_bool("CORREO_ACTIVO", False),
        smtp_host=_texto("SMTP_HOST"),
        smtp_puerto=_entero("SMTP_PUERTO", 587),
        smtp_usuario=_texto("SMTP_USUARIO"),
        smtp_clave=os.getenv("SMTP_CLAVE") or "",
        smtp_tls=_bool("SMTP_TLS", True),
        correo_remitente=_texto("CORREO_REMITENTE"),
        correo_destinatarios=destinatarios,
    )
    return actual


actual: Config = cargar()


def ahora() -> datetime:
    """Fecha y hora local (sin zona) según ZONA_HORARIA."""
    try:
        zona = ZoneInfo(actual.zona)
    except Exception:  # zona mal escrita: se usa la del sistema
        return datetime.now().replace(microsecond=0)
    return datetime.now(zona).replace(tzinfo=None, microsecond=0)


def hoy() -> date:
    return ahora().date()
