"""Cuentas por pagar: registro de facturas, pago y exportación del archivo de pago masivo."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import config, credito, exportacion, servicios
from ..db import get_db
from ..modelos import ESTADOS_FACTURA, FACTURA_PENDIENTE, Factura, Proveedor, Usuario
from ..servicios import ErrorNegocio
from ..web import aviso, entero, es_htmx, fecha_de, ir, puede_editar, render, ruta_segura, usuario_actual

router = APIRouter()

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _factura(sesion: Session, fid: int) -> Factura:
    f = sesion.get(Factura, fid)
    if f is None:
        raise HTTPException(status_code=404)
    return f


def _despues(request: Request, destino: str):
    """Tras una acción: HTMX recarga la pantalla; un formulario normal redirige."""
    if es_htmx(request):
        return Response(status_code=200, headers={"HX-Refresh": "true"})
    return ir(destino)


@router.get("/facturas")
def listado(
    request: Request,
    q: str = "",
    estado: str = FACTURA_PENDIENTE,
    u: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(get_db),
):
    consulta = select(Factura).join(Proveedor, Factura.proveedor_id == Proveedor.id)
    texto = (q or "").strip()
    if texto:
        consulta = consulta.where(
            or_(Proveedor.nombre_norm.like(f"%{servicios.normalizar(texto)}%"), Factura.numero.like(f"%{texto}%"))
        )
    if estado in ESTADOS_FACTURA:
        consulta = consulta.where(Factura.estado == estado)
    facturas = sesion.scalars(consulta.order_by(Factura.vencimiento, Factura.id).limit(1000)).all()
    filas = [{"f": f, "bloqueo": exportacion.motivo_bloqueo(f)} for f in facturas]
    return render(
        request,
        "facturas.html",
        filas=filas,
        filtros={"q": q, "estado": estado},
        total=servicios.totales(facturas),
    )


def _proveedores_activos(sesion: Session):
    return sesion.scalars(select(Proveedor).where(Proveedor.activo.is_(True)).order_by(Proveedor.nombre_norm)).all()


@router.get("/facturas/nueva")
def pantalla_nueva(
    request: Request,
    proveedor: str = "",
    u: Usuario = Depends(puede_editar),
    sesion: Session = Depends(get_db),
):
    datos = {"proveedor_id": entero(proveedor), "fecha": config.hoy().isoformat(), "moneda": "USD"}
    return render(request, "factura_form.html", datos=datos, proveedores=_proveedores_activos(sesion), errores=[])


@router.post("/facturas/nueva")
async def crear(request: Request, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    formulario = await request.form()
    datos = {
        "proveedor_id": entero(formulario.get("proveedor_id")),
        "numero": str(formulario.get("numero") or "").strip(),
        "fecha": str(formulario.get("fecha") or "").strip(),
        "valor": str(formulario.get("valor") or "").strip(),
        "moneda": str(formulario.get("moneda") or "USD").strip().upper(),
        "notas": str(formulario.get("notas") or "").strip(),
    }
    errores = []
    p = sesion.get(Proveedor, datos["proveedor_id"]) if datos["proveedor_id"] else None
    if p is None:
        errores.append("Elija el proveedor.")
    fecha = fecha_de(datos["fecha"])
    if fecha is None:
        errores.append("La fecha de la factura no es válida.")
    centavos = None
    try:
        centavos = servicios.interpretar_valor(datos["valor"])
    except ErrorNegocio as error:
        errores.append(str(error))
    if not errores:
        try:
            f = servicios.crear_factura(sesion, p, datos["numero"], fecha, centavos, datos["moneda"], u, datos["notas"])
            sesion.commit()
        except ErrorNegocio as error:
            sesion.rollback()
            errores.append(str(error))
    if errores:
        return render(
            request,
            "factura_form.html",
            status_code=400,
            datos=datos,
            proveedores=_proveedores_activos(sesion),
            errores=errores,
        )
    mensaje = f"Factura registrada. Vence el {f.vencimiento:%d/%m/%Y} ({credito.texto(p.credito_tipo, p.credito_valor)})."
    aviso(request, mensaje)
    if not p.credito_tipo:
        aviso(request, "El proveedor no tiene condición de crédito: la factura se trató como de contado.", "alerta")
    return ir("/facturas")


@router.post("/facturas/exportar")
async def exportar(request: Request, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    formulario = await request.form()
    ids = [i for i in (entero(v) for v in formulario.getlist("ids")) if i is not None]
    if not ids:
        aviso(request, "Seleccione al menos una factura para exportar.", "alerta")
        return ir("/facturas")
    facturas = sesion.scalars(
        select(Factura).where(Factura.id.in_(ids)).order_by(Factura.vencimiento, Factura.id)
    ).all()
    bloqueadas = [(f, exportacion.motivo_bloqueo(f)) for f in facturas]
    bloqueadas = [(f, motivo) for f, motivo in bloqueadas if motivo]
    if bloqueadas or not facturas:
        # Se rechaza todo el archivo: un pago a un proveedor sin aprobar no debe salir nunca.
        return render(
            request,
            "error.html",
            status_code=400,
            titulo="No se generó el archivo de pago",
            detalle="Estas facturas no se pueden incluir. Quítelas de la selección o resuelva el motivo:",
            lineas=[f"Factura {f.numero} — {f.proveedor.nombre}: {motivo}" for f, motivo in bloqueadas],
            volver="/facturas",
        )
    contenido = exportacion.a_bytes(exportacion.libro_pago_masivo(facturas, servicios.contrapartida(sesion)))
    ahora = config.ahora()
    for f in facturas:
        f.exportada_en = ahora
    sesion.commit()
    nombre = f"pago-masivo-{ahora:%Y%m%d-%H%M}.xlsx"
    return Response(contenido, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.post("/facturas/{fid}/pagar")
async def pagar(request: Request, fid: int, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    f = _factura(sesion, fid)
    formulario = await request.form()
    try:
        servicios.marcar_pagada(sesion, f, u, fecha_de(formulario.get("fecha_pago")))
        sesion.commit()
        aviso(request, f"Factura {f.numero} marcada como pagada.")
    except ErrorNegocio as error:
        sesion.rollback()
        aviso(request, str(error), "error")
    return _despues(request, ruta_segura(formulario.get("siguiente"), "/facturas"))


@router.post("/facturas/{fid}/reabrir")
async def reabrir(request: Request, fid: int, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    f = _factura(sesion, fid)
    formulario = await request.form()
    try:
        servicios.reabrir_factura(sesion, f)
        sesion.commit()
        aviso(request, f"Factura {f.numero} vuelve a estar pendiente.", "alerta")
    except ErrorNegocio as error:
        sesion.rollback()
        aviso(request, str(error), "error")
    return _despues(request, ruta_segura(formulario.get("siguiente"), "/facturas"))


@router.post("/facturas/{fid}/anular")
async def anular(request: Request, fid: int, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    f = _factura(sesion, fid)
    formulario = await request.form()
    try:
        servicios.anular_factura(sesion, f)
        sesion.commit()
        aviso(request, f"Factura {f.numero} anulada.", "alerta")
    except ErrorNegocio as error:
        sesion.rollback()
        aviso(request, str(error), "error")
    return _despues(request, ruta_segura(formulario.get("siguiente"), "/facturas"))
