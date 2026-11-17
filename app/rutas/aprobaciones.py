"""Revisión de proveedores: la hace una persona distinta de quien los creó o modificó."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import servicios, validaciones
from ..db import get_db
from ..modelos import PENDIENTE, RECHAZADO, Historial, Proveedor, Usuario
from ..servicios import ErrorNegocio
from ..web import aviso, entero, ir, puede_aprobar, render, ruta_segura

router = APIRouter()


def _proveedor(sesion: Session, pid: int) -> Proveedor:
    p = sesion.get(Proveedor, pid)
    if p is None:
        raise HTTPException(status_code=404)
    return p


@router.get("/aprobaciones")
def pantalla(request: Request, u: Usuario = Depends(puede_aprobar), sesion: Session = Depends(get_db)):
    pendientes = sesion.scalars(
        select(Proveedor)
        .where(Proveedor.estado_aprobacion == PENDIENTE, Proveedor.activo.is_(True))
        .order_by(Proveedor.modificado_en, Proveedor.id)
    ).all()
    avisos_por_id = {}
    for grupo in validaciones.revisar(sesion):
        for caso in grupo["casos"]:
            avisos_por_id.setdefault(caso["proveedor"].id, []).append(
                {"titulo": grupo["titulo"], "severidad": grupo["severidad"], "detalle": caso["detalle"]}
            )
    tarjetas = [
        {
            "p": p,
            "cambios": servicios.cambios_por_revisar(sesion, p),
            "avisos": avisos_por_id.get(p.id, []),
            "bloqueo": servicios.motivo_no_puede_aprobar(p, u),
        }
        for p in pendientes
    ]
    rechazados = sesion.scalars(
        select(Proveedor)
        .where(Proveedor.estado_aprobacion == RECHAZADO, Proveedor.activo.is_(True))
        .order_by(Proveedor.aprobado_en.desc())
        .limit(50)
    ).all()
    decisiones = sesion.scalars(
        select(Historial)
        .where(Historial.tipo.in_(("aprobacion", "rechazo")))
        .order_by(Historial.fecha.desc(), Historial.id.desc())
        .limit(20)
    ).all()
    return render(
        request,
        "aprobaciones.html",
        tarjetas=tarjetas,
        aprobables=sum(1 for t in tarjetas if not t["bloqueo"]),
        rechazados=rechazados,
        decisiones=decisiones,
        empresas_cols=servicios.empresas_visibles(sesion, u),
    )


@router.post("/aprobaciones/lote")
async def aprobar_lote(request: Request, u: Usuario = Depends(puede_aprobar), sesion: Session = Depends(get_db)):
    formulario = await request.form()
    ids = [i for i in (entero(v) for v in formulario.getlist("ids")) if i is not None]
    if not ids:
        aviso(request, "No seleccionó ningún proveedor.", "alerta")
        return ir("/aprobaciones")
    aprobados, omitidos = 0, 0
    for p in sesion.scalars(select(Proveedor).where(Proveedor.id.in_(ids))).all():
        try:
            servicios.aprobar(sesion, p, u)
            aprobados += 1
        except ErrorNegocio:
            omitidos += 1
    sesion.commit()
    if aprobados:
        aviso(request, f"Proveedores revisados: {aprobados}.")
    if omitidos:
        aviso(request, f"No se marcaron como revisados {omitidos}: no están pendientes o usted los creó o modificó.", "alerta")
    return ir("/aprobaciones")


@router.post("/aprobaciones/{pid}/aprobar")
async def aprobar(request: Request, pid: int, u: Usuario = Depends(puede_aprobar), sesion: Session = Depends(get_db)):
    p = _proveedor(sesion, pid)
    formulario = await request.form()
    destino = ruta_segura(formulario.get("siguiente"), "/aprobaciones")
    try:
        servicios.aprobar(sesion, p, u)
        sesion.commit()
        aviso(request, f"Revisado: {p.nombre}.")
    except ErrorNegocio as error:
        sesion.rollback()
        aviso(request, str(error), "error")
    return ir(destino)


@router.post("/aprobaciones/{pid}/rechazar")
async def rechazar(request: Request, pid: int, u: Usuario = Depends(puede_aprobar), sesion: Session = Depends(get_db)):
    p = _proveedor(sesion, pid)
    formulario = await request.form()
    destino = ruta_segura(formulario.get("siguiente"), "/aprobaciones")
    try:
        servicios.rechazar(sesion, p, u, str(formulario.get("motivo") or ""))
        sesion.commit()
        aviso(request, f"Rechazado: {p.nombre}.", "alerta")
    except ErrorNegocio as error:
        sesion.rollback()
        aviso(request, str(error), "error")
    return ir(destino)
