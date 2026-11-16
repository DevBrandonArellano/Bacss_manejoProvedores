"""Validaciones, historial, catálogos, usuarios y configuración."""
import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from .. import catalogos, config, servicios, tareas, validaciones
from ..db import get_db
from ..modelos import ROLES, Banco, Historial, Proveedor, TipoCuenta, TipoId, Usuario
from ..servicios import ErrorNegocio
from ..web import aviso, entero, es_htmx, ir, render, requiere_facturacion, solo_admin, usuario_actual

router = APIRouter()

TAMANO_MAXIMO_EXCEL = 15 * 1024 * 1024
CLASES_TIPO = {"tipos-id": (TipoId, "Tipo de ID"), "tipos-cuenta": (TipoCuenta, "Tipo de cuenta")}


# ---------------------------------------------------------------- validaciones e historial


@router.get("/validaciones")
def pantalla_validaciones(request: Request, u: Usuario = Depends(usuario_actual), sesion: Session = Depends(get_db)):
    grupos = validaciones.revisar(sesion)
    return render(request, "validaciones.html", grupos=grupos, total=sum(len(g["casos"]) for g in grupos))


@router.get("/historial")
def pantalla_historial(
    request: Request,
    q: str = "",
    solo: str = "",
    u: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(get_db),
):
    consulta = select(Historial).join(Proveedor, Historial.proveedor_id == Proveedor.id)
    texto = (q or "").strip()
    if texto:
        patron = f"%{servicios.normalizar(texto)}%"
        consulta = consulta.where(or_(Proveedor.nombre_norm.like(patron), Historial.usuario_nombre.like(f"%{texto}%")))
    if solo == "bancarios":
        consulta = consulta.where(Historial.sensible.is_(True))
    elif solo == "aprobaciones":
        consulta = consulta.where(Historial.tipo.in_(("aprobacion", "rechazo")))
    movimientos = sesion.scalars(consulta.order_by(Historial.fecha.desc(), Historial.id.desc()).limit(500)).all()
    return render(request, "historial.html", movimientos=movimientos, filtros={"q": q, "solo": solo})


# ---------------------------------------------------------------- catálogos


def _bancos(sesion: Session, q: str):
    consulta = select(Banco)
    texto = (q or "").strip()
    if texto:
        consulta = consulta.where(
            or_(Banco.nombre_norm.like(f"%{servicios.normalizar(texto)}%"), Banco.codigo.like(f"{texto}%"))
        )
    return sesion.scalars(consulta.order_by(Banco.nombre_norm, Banco.codigo)).all()


def _pantalla_catalogos(request: Request, sesion: Session, q: str = "", resumen=None, status_code: int = 200):
    cfg = config.actual
    return render(
        request,
        "catalogos.html",
        status_code=status_code,
        bancos=_bancos(sesion, q),
        q=q,
        tipos_id=sesion.scalars(select(TipoId).order_by(TipoId.codigo)).all(),
        tipos_cuenta=sesion.scalars(select(TipoCuenta).order_by(TipoCuenta.codigo)).all(),
        resumen=resumen,
        excel_en_servidor=cfg.ruta_excel.is_file(),
        hoja_catalogos=catalogos.HOJA_CATALOGOS,
    )


@router.get("/catalogos")
def pantalla_catalogos(request: Request, q: str = "", u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)):
    if es_htmx(request):
        return render(request, "_bancos_tabla.html", bancos=_bancos(sesion, q))
    return _pantalla_catalogos(request, sesion, q)


@router.post("/catalogos/cargar-excel")
async def cargar_excel(request: Request, u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)):
    """Agrega catálogos desde la hoja de catálogos del Excel. No lee la hoja de proveedores."""
    formulario = await request.form()
    archivo = formulario.get("archivo")
    cfg = config.actual
    try:
        if isinstance(archivo, UploadFile) and archivo.filename:
            contenido = await archivo.read(TAMANO_MAXIMO_EXCEL + 1)
            if len(contenido) > TAMANO_MAXIMO_EXCEL:
                raise ErrorNegocio("El archivo es demasiado grande.")
            origen = io.BytesIO(contenido)
        elif cfg.ruta_excel.is_file():
            origen = cfg.ruta_excel
        else:
            raise ErrorNegocio("Elija el archivo Excel que contiene la hoja de catálogos.")
        resumen = catalogos.cargar_desde_excel(sesion, origen)
    except ErrorNegocio as error:
        sesion.rollback()
        aviso(request, str(error), "error")
        return ir("/catalogos")
    return _pantalla_catalogos(request, sesion, resumen=resumen)


@router.post("/catalogos/bancos/nuevo")
async def banco_nuevo(request: Request, u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)):
    formulario = await request.form()
    codigo = str(formulario.get("codigo") or "").strip()
    nombre = str(formulario.get("nombre") or "").strip()
    if not codigo or not nombre:
        aviso(request, "Escriba el código oficial y el nombre de la institución.", "error")
    elif sesion.scalars(select(Banco).where(Banco.codigo == codigo, Banco.nombre == nombre)).first() is not None:
        aviso(request, "Ya existe una institución con ese código y ese nombre.", "error")
    else:
        sesion.add(Banco(codigo=codigo, nombre=nombre, nombre_norm=servicios.normalizar(nombre), activo=True))
        sesion.commit()
        aviso(request, f"Institución agregada: {nombre} (código {codigo}).")
    return ir("/catalogos")


@router.post("/catalogos/bancos/{bid}")
async def banco_editar(request: Request, bid: int, u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)):
    banco = sesion.get(Banco, bid)
    if banco is None:
        raise HTTPException(status_code=404)
    formulario = await request.form()
    codigo = str(formulario.get("codigo") or "").strip()
    nombre = str(formulario.get("nombre") or "").strip()
    activo = formulario.get("activo") == "1"
    repetido = sesion.scalars(
        select(Banco).where(Banco.codigo == codigo, Banco.nombre == nombre, Banco.id != banco.id)
    ).first()
    if not codigo or not nombre:
        aviso(request, "El código y el nombre no pueden quedar vacíos.", "error")
    elif repetido is not None:
        aviso(request, "Ya existe otra institución con ese código y ese nombre.", "error")
    else:
        if codigo != banco.codigo:
            aviso(request, f"Cambió el código oficial de {banco.codigo} a {codigo}. Verifique que sea correcto.", "alerta")
        banco.codigo, banco.nombre, banco.activo = codigo, nombre, activo
        banco.nombre_norm = servicios.normalizar(nombre)
        sesion.commit()
        aviso(request, f"Institución actualizada: {nombre}.")
    return ir("/catalogos?q=" + quote(codigo) if codigo else "/catalogos")


@router.post("/catalogos/{clase}/nuevo")
async def tipo_nuevo(request: Request, clase: str, u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)):
    if clase not in CLASES_TIPO:
        raise HTTPException(status_code=404)
    modelo, etiqueta = CLASES_TIPO[clase]
    formulario = await request.form()
    codigo = str(formulario.get("codigo") or "").strip().upper()
    nombre = str(formulario.get("nombre") or "").strip().upper()
    if not codigo or not nombre:
        aviso(request, "Escriba el código y el nombre.", "error")
    elif sesion.scalars(select(modelo).where(modelo.codigo == codigo)).first() is not None:
        aviso(request, f"Ya existe un {etiqueta.lower()} con ese código.", "error")
    else:
        sesion.add(modelo(codigo=codigo, nombre=nombre, activo=True))
        sesion.commit()
        aviso(request, f"{etiqueta} agregado: {nombre}.")
    return ir("/catalogos")


@router.post("/catalogos/{clase}/{tid}")
async def tipo_editar(
    request: Request, clase: str, tid: int, u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)
):
    if clase not in CLASES_TIPO:
        raise HTTPException(status_code=404)
    modelo, etiqueta = CLASES_TIPO[clase]
    fila = sesion.get(modelo, tid)
    if fila is None:
        raise HTTPException(status_code=404)
    formulario = await request.form()
    codigo = str(formulario.get("codigo") or "").strip().upper()
    nombre = str(formulario.get("nombre") or "").strip().upper()
    repetido = sesion.scalars(select(modelo).where(modelo.codigo == codigo, modelo.id != fila.id)).first()
    if not codigo or not nombre:
        aviso(request, "El código y el nombre no pueden quedar vacíos.", "error")
    elif repetido is not None:
        aviso(request, f"Ya existe otro {etiqueta.lower()} con ese código.", "error")
    else:
        fila.codigo, fila.nombre, fila.activo = codigo, nombre, formulario.get("activo") == "1"
        sesion.commit()
        aviso(request, f"{etiqueta} actualizado: {nombre}.")
    return ir("/catalogos")


# ---------------------------------------------------------------- usuarios


@router.get("/usuarios")
def pantalla_usuarios(request: Request, u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)):
    lista = sesion.scalars(select(Usuario).order_by(Usuario.usuario)).all()
    return render(request, "usuarios.html", lista=lista)


@router.post("/usuarios/nuevo")
async def usuario_nuevo(request: Request, u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)):
    formulario = await request.form()
    try:
        nuevo = servicios.crear_usuario(
            sesion,
            str(formulario.get("usuario") or ""),
            str(formulario.get("nombre") or ""),
            str(formulario.get("clave") or ""),
            str(formulario.get("rol") or ""),
        )
        sesion.commit()
        aviso(request, f"Usuario creado: {nuevo.usuario} ({ROLES[nuevo.rol]}).")
    except ErrorNegocio as error:
        sesion.rollback()
        aviso(request, str(error), "error")
    return ir("/usuarios")


@router.post("/usuarios/{uid}")
async def usuario_editar(request: Request, uid: int, u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)):
    objetivo = sesion.get(Usuario, uid)
    if objetivo is None:
        raise HTTPException(status_code=404)
    formulario = await request.form()
    try:
        servicios.actualizar_usuario(
            sesion,
            objetivo,
            str(formulario.get("nombre") or ""),
            str(formulario.get("rol") or ""),
            formulario.get("activo") == "1",
            str(formulario.get("clave") or ""),
        )
        sesion.commit()
        aviso(request, f"Usuario actualizado: {objetivo.usuario}.")
    except ErrorNegocio as error:
        sesion.rollback()
        aviso(request, str(error), "error")
    return ir("/usuarios")


# ---------------------------------------------------------------- configuración


def _pantalla_configuracion(request: Request, sesion: Session):
    cfg = config.actual
    respaldos = tareas.listar_respaldos(cfg.ruta_respaldos)
    return render(
        request,
        "configuracion.html",
        dias_aviso=servicios.dias_aviso(sesion),
        contrapartida=servicios.contrapartida(sesion),
        ultima_revision=servicios.cfg_leer(sesion, "ultima_revision"),
        cfg=cfg,
        respaldos=[r.name for r in respaldos[:10]],
        total_respaldos=len(respaldos),
    )


@router.get("/configuracion")
def pantalla_configuracion(request: Request, u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)):
    return _pantalla_configuracion(request, sesion)


@router.post("/configuracion", dependencies=[Depends(requiere_facturacion)])
async def guardar_configuracion(request: Request, u: Usuario = Depends(solo_admin), sesion: Session = Depends(get_db)):
    formulario = await request.form()
    dias = entero(formulario.get("dias_aviso"))
    contrapartida = str(formulario.get("contrapartida") or "").strip()
    if dias is None or not 0 <= dias <= 365:
        aviso(request, "Los días de aviso deben estar entre 0 y 365.", "error")
    elif not contrapartida or len(contrapartida) > 30:
        aviso(request, "La contrapartida no puede quedar vacía (máximo 30 caracteres).", "error")
    else:
        servicios.cfg_guardar(sesion, "dias_aviso", dias)
        servicios.cfg_guardar(sesion, "contrapartida", contrapartida)
        sesion.commit()
        aviso(request, "Configuración guardada.")
    return ir("/configuracion")


@router.post("/configuracion/respaldar")
def respaldar_ahora(request: Request, u: Usuario = Depends(solo_admin)):
    try:
        destino = tareas.respaldar()
        aviso(request, f"Respaldo creado: {destino.name}.")
    except Exception as error:
        aviso(request, f"No se pudo crear el respaldo ({type(error).__name__}). Revise la carpeta de respaldos.", "error")
    return ir("/configuracion")


@router.post("/configuracion/revisar-alarmas", dependencies=[Depends(requiere_facturacion)])
def revisar_ahora(request: Request, u: Usuario = Depends(solo_admin)):
    try:
        tareas.revisar_alarmas()
        aviso(request, "Revisión de alarmas ejecutada.")
    except Exception as error:
        aviso(request, f"No se pudo ejecutar la revisión ({type(error).__name__}).", "error")
    return ir("/configuracion")
