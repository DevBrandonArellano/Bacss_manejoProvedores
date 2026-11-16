"""Aplicación web Manejo de Proveedores."""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as ErrorHttp
from starlette.middleware.sessions import SessionMiddleware

from . import catalogos, config, db, tareas
from .modelos import Usuario
from .rutas import administracion, aprobaciones, facturas, proveedores, sesion
from .web import DIRECTORIO, ErrorCsrf, NoAutenticado, SinPermiso, es_htmx, ir, render, verificar_csrf

registro = logging.getLogger("proveedores")


@asynccontextmanager
async def ciclo(app: FastAPI):
    cfg = config.actual
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.iniciar_bd(cfg.ruta_bd)
    with db.SessionLocal() as s:
        catalogos.preparar_bd(s)
        if s.scalar(select(func.count()).select_from(Usuario)) == 0:
            registro.warning("No hay usuarios. Defina ADMIN_USUARIO y ADMIN_CLAVE en .env y reinicie.")
    if cfg.clave_sesion_generada:
        registro.warning("CLAVE_SESION no está definida (o es muy corta): las sesiones se cerrarán en cada reinicio.")
    programador = tareas.iniciar_programador()
    try:
        yield
    finally:
        if programador is not None:
            programador.shutdown(wait=False)
        db.cerrar_bd()


def crear_app() -> FastAPI:
    cfg = config.cargar()
    app = FastAPI(
        title="Manejo de Proveedores",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=ciclo,
        dependencies=[Depends(verificar_csrf)],
    )

    @app.middleware("http")
    async def cabeceras(request: Request, llamar):
        respuesta = await llamar(request)
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("Referrer-Policy", "same-origin")
        if not request.url.path.startswith("/static"):
            # Datos bancarios: que el navegador no guarde copias de las pantallas.
            respuesta.headers.setdefault("Cache-Control", "no-store")
        return respuesta

    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.clave_sesion,
        session_cookie="proveedores_sesion",
        max_age=12 * 3600,
        same_site="lax",
        https_only=cfg.cookie_segura,
    )
    app.mount("/static", StaticFiles(directory=str(DIRECTORIO / "static")), name="static")

    for modulo in (sesion, proveedores, aprobaciones, facturas, administracion):
        app.include_router(modulo.router)

    @app.get("/salud", include_in_schema=False)
    def salud():
        return JSONResponse({"estado": "ok"})

    @app.exception_handler(NoAutenticado)
    async def sin_sesion(request: Request, _error: NoAutenticado):
        if es_htmx(request):
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        return ir("/login")

    @app.exception_handler(SinPermiso)
    async def sin_permiso(request: Request, _error: SinPermiso):
        return render(
            request,
            "error.html",
            status_code=403,
            titulo="Sin permiso",
            detalle="Su perfil no tiene permiso para hacer esto.",
        )

    @app.exception_handler(ErrorCsrf)
    async def csrf_invalido(request: Request, _error: ErrorCsrf):
        return render(
            request,
            "error.html",
            status_code=403,
            titulo="Formulario vencido",
            detalle="Por seguridad, vuelva a la pantalla anterior, recárguela e inténtelo de nuevo.",
        )

    @app.exception_handler(ErrorHttp)
    async def error_http(request: Request, error: ErrorHttp):
        if error.status_code == 404:
            titulo, detalle = "No encontrado", "La página o el registro que busca no existe."
        else:
            titulo, detalle = f"Error {error.status_code}", "No se pudo completar la operación."
        return render(request, "error.html", status_code=error.status_code, titulo=titulo, detalle=detalle)

    return app


app = crear_app()
