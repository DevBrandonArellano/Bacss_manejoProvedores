"""Piezas comunes de las pantallas: plantillas, sesión, permisos y protección CSRF."""
import secrets
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import VERSION, config, credito, modelos, servicios
from .db import get_db
from .modelos import Usuario

DIRECTORIO = Path(__file__).resolve().parent
plantillas = Jinja2Templates(directory=str(DIRECTORIO / "templates"))


class NoAutenticado(Exception):
    pass


class SinPermiso(Exception):
    pass


class ErrorCsrf(Exception):
    pass


# ---------------------------------------------------------------- filtros de plantilla


def _dinero(valor) -> str:
    if valor is None:
        return ""
    return f"{Decimal(valor):,.2f}"


def _fecha(valor) -> str:
    if not valor:
        return ""
    return valor.strftime("%d/%m/%Y")


def _fechahora(valor) -> str:
    if not valor:
        return ""
    return valor.strftime("%d/%m/%Y %H:%M")


def _enmascarar(valor) -> str:
    """Muestra solo los últimos 4 caracteres de una cuenta."""
    if not valor:
        return ""
    texto = str(valor)
    return "••••" + texto[-4:] if len(texto) > 4 else texto


plantillas.env.filters["dinero"] = _dinero
plantillas.env.filters["fecha"] = _fecha
plantillas.env.filters["fechahora"] = _fechahora
plantillas.env.filters["enmascarar"] = _enmascarar
plantillas.env.globals["ROLES"] = modelos.ROLES
plantillas.env.globals["ESTADOS_APROBACION"] = modelos.ESTADOS_APROBACION
plantillas.env.globals["ESTADOS_FACTURA"] = modelos.ESTADOS_FACTURA
plantillas.env.globals["TIPOS_CREDITO"] = credito.TIPOS
plantillas.env.globals["VERSION"] = VERSION


# ---------------------------------------------------------------- sesión y CSRF


def token_csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def verificar_csrf(request: Request) -> None:
    """Toda petición que modifica datos debe traer el token de la sesión (campo oculto o cabecera)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    esperado = request.session.get("csrf")
    enviado = request.headers.get("X-CSRF-Token")
    if not enviado:
        tipo = request.headers.get("content-type", "")
        if tipo.startswith("application/x-www-form-urlencoded") or tipo.startswith("multipart/form-data"):
            formulario = await request.form()
            enviado = formulario.get("csrf_token")
    if not esperado or not isinstance(enviado, str):
        raise ErrorCsrf()
    if not secrets.compare_digest(str(esperado).encode("utf-8"), enviado.encode("utf-8")):
        raise ErrorCsrf()


def huella(u: Usuario) -> str:
    """Cambia cuando cambia la contraseña: cierra las sesiones abiertas con la clave anterior."""
    return u.clave_hash[-16:]


def iniciar_sesion(request: Request, u: Usuario) -> None:
    request.session.clear()
    request.session["uid"] = u.id
    request.session["sv"] = huella(u)
    token_csrf(request)


def usuario_actual(request: Request, sesion: Session = Depends(get_db)) -> Usuario:
    uid = request.session.get("uid")
    u = sesion.get(Usuario, uid) if uid else None
    if u is None or not u.activo or request.session.get("sv") != huella(u):
        request.session.pop("uid", None)
        raise NoAutenticado()
    request.state.usuario = u
    request.state.pendientes = servicios.contar_pendientes(sesion)
    return u


def requiere(*roles: str):
    """Dependencia que exige uno de los perfiles indicados."""

    def dependencia(u: Usuario = Depends(usuario_actual)) -> Usuario:
        if u.rol not in roles:
            raise SinPermiso()
        return u

    return dependencia


solo_admin = requiere(modelos.ADMINISTRADOR)
puede_editar = requiere(modelos.ADMINISTRADOR, modelos.CREADOR)
puede_aprobar = requiere(modelos.ADMINISTRADOR, modelos.APROBADOR)


# ---------------------------------------------------------------- respuestas


def es_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def aviso(request: Request, texto: str, tipo: str = "ok") -> None:
    """Mensaje que se muestra una vez en la siguiente pantalla. tipo: ok | error | alerta."""
    mensajes = list(request.session.get("flash", []))
    mensajes.append([tipo, texto[:300]])
    request.session["flash"] = mensajes[-4:]


def render(request: Request, plantilla: str, status_code: int = 200, **contexto):
    contexto.setdefault("usuario", getattr(request.state, "usuario", None))
    contexto["pendientes"] = getattr(request.state, "pendientes", 0)
    contexto["csrf"] = token_csrf(request)
    contexto["mensajes"] = request.session.pop("flash", [])
    contexto["hoy"] = config.hoy()
    contexto["ruta_actual"] = request.url.path
    return plantillas.TemplateResponse(request, plantilla, contexto, status_code=status_code)


def ruta_segura(url, defecto: str = "/") -> str:
    """Solo se redirige a rutas locales de la propia app."""
    if isinstance(url, str) and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return defecto


def ir(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def entero(valor) -> Optional[int]:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def fecha_de(valor) -> Optional[date]:
    try:
        return datetime.strptime(str(valor).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
