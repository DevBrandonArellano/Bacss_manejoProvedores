"""Inicio de sesión, cambio de contraseña y panel de alarmas."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, seguridad, servicios
from ..db import get_db
from ..modelos import Usuario
from ..web import aviso, entero, iniciar_sesion, ir, render, usuario_actual

router = APIRouter()


@router.get("/login")
def pantalla_login(request: Request, sesion: Session = Depends(get_db)):
    uid = request.session.get("uid")
    if uid and sesion.get(Usuario, uid) is not None:
        return ir("/")
    return render(request, "login.html", error=None, usuario_escrito="")


@router.post("/login")
async def entrar(request: Request, sesion: Session = Depends(get_db)):
    formulario = await request.form()
    nombre_usuario = str(formulario.get("usuario") or "").strip().lower()
    clave = str(formulario.get("clave") or "")
    origen = request.client.host if request.client else "-"
    llave = f"{origen}|{nombre_usuario}"
    if seguridad.bloqueado(llave):
        return render(
            request,
            "login.html",
            status_code=429,
            error="Demasiados intentos fallidos. Espere unos minutos e inténtelo de nuevo.",
            usuario_escrito=nombre_usuario,
        )
    u = sesion.scalars(select(Usuario).where(Usuario.usuario == nombre_usuario)).first()
    if u is None or not u.activo or not seguridad.verificar(u.clave_hash, clave):
        seguridad.registrar_fallo(llave)
        return render(
            request,
            "login.html",
            status_code=401,
            error="Usuario o contraseña incorrectos.",
            usuario_escrito=nombre_usuario,
        )
    seguridad.limpiar_fallos(llave)
    iniciar_sesion(request, u)
    return ir("/")


@router.post("/salir")
def salir(request: Request):
    request.session.clear()
    return ir("/login")


@router.get("/mi-clave")
def pantalla_clave(request: Request, u: Usuario = Depends(usuario_actual)):
    return render(request, "mi_clave.html", error=None)


@router.post("/mi-clave")
async def cambiar_clave(request: Request, u: Usuario = Depends(usuario_actual), sesion: Session = Depends(get_db)):
    formulario = await request.form()
    actual = str(formulario.get("actual") or "")
    nueva = str(formulario.get("nueva") or "")
    repetida = str(formulario.get("repetida") or "")
    error = None
    if not seguridad.verificar(u.clave_hash, actual):
        error = "La contraseña actual no es correcta."
    elif nueva != repetida:
        error = "La contraseña nueva y su repetición no coinciden."
    else:
        error = seguridad.error_clave(nueva)
    if error:
        return render(request, "mi_clave.html", status_code=400, error=error)
    u.clave_hash = seguridad.cifrar(nueva)
    sesion.commit()
    iniciar_sesion(request, u)
    aviso(request, "Contraseña cambiada.")
    return ir("/")


@router.get("/")
def panel(request: Request, dias: str = "", u: Usuario = Depends(usuario_actual), sesion: Session = Depends(get_db)):
    if not config.actual.facturacion_activa:
        return ir("/proveedores")
    configurado = servicios.dias_aviso(sesion)
    elegido = entero(dias)
    n = configurado if elegido is None else max(0, min(elegido, 365))
    hoy = config.hoy()
    grupos = servicios.facturas_por_vencer(sesion, hoy, n)
    return render(
        request,
        "panel.html",
        grupos=grupos,
        totales={clave: servicios.totales(lista) for clave, lista in grupos.items()},
        dias=n,
        dias_configurado=configurado,
        ultima_revision=servicios.cfg_leer(sesion, "ultima_revision"),
    )
