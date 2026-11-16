"""Proveedores: listado, búsqueda, alta, edición, desactivación y exportación."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import config, credito, exportacion, servicios, validaciones
from ..db import get_db
from ..modelos import ESTADOS_APROBACION, Banco, Factura, Historial, Proveedor, TipoCuenta, TipoId, Usuario
from ..web import aviso, entero, es_htmx, ir, puede_editar, render, usuario_actual

router = APIRouter()

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _proveedor(sesion: Session, pid: int) -> Proveedor:
    p = sesion.get(Proveedor, pid)
    if p is None:
        raise HTTPException(status_code=404)
    return p


def _filtrar(sesion: Session, q: str, banco: str, aprobacion: str, estado: str, registrado: str):
    consulta = select(Proveedor).outerjoin(Banco, Proveedor.banco_id == Banco.id)
    texto = (q or "").strip()
    if texto:
        patron = f"%{servicios.normalizar(texto)}%"
        compacto = f"%{servicios.sin_espacios(texto)}%"
        consulta = consulta.where(
            or_(
                Proveedor.nombre_norm.like(patron),
                Proveedor.numero_id.like(compacto),
                Proveedor.numero_cuenta.like(compacto),
                Banco.nombre_norm.like(patron),
            )
        )
    banco_id = entero(banco)
    if banco_id is not None:
        consulta = consulta.where(Proveedor.banco_id == banco_id)
    if aprobacion in ESTADOS_APROBACION:
        consulta = consulta.where(Proveedor.estado_aprobacion == aprobacion)
    if estado == "inactivos":
        consulta = consulta.where(Proveedor.activo.is_(False))
    elif estado != "todos":
        consulta = consulta.where(Proveedor.activo.is_(True))
    if registrado == "si":
        consulta = consulta.where(Proveedor.registrado_banco.is_(True))
    elif registrado == "no":
        consulta = consulta.where(Proveedor.registrado_banco.is_(False))
    return sesion.scalars(consulta.order_by(Proveedor.nombre_norm)).all()


def _opciones(sesion: Session, p: Proveedor = None) -> dict:
    """Opciones de los desplegables: las activas, más la que ya tenga el proveedor aunque esté inactiva."""

    def lista(modelo, actual_id, orden):
        filas = sesion.scalars(select(modelo).where(modelo.activo.is_(True)).order_by(orden)).all()
        if actual_id and all(f.id != actual_id for f in filas):
            actual = sesion.get(modelo, actual_id)
            if actual is not None:
                filas = [actual] + list(filas)
        return filas

    return {
        "tipos_id": lista(TipoId, p.tipo_id_id if p else None, TipoId.nombre),
        "tipos_cuenta": lista(TipoCuenta, p.tipo_cuenta_id if p else None, TipoCuenta.nombre),
        "bancos": lista(Banco, p.banco_id if p else None, Banco.nombre),
    }


def _datos_formulario(formulario) -> dict:
    opcion = str(formulario.get("credito") or "")
    if opcion == "contado":
        tipo, valor = credito.DIAS, 0
    elif opcion == credito.DIAS:
        tipo, valor = credito.DIAS, entero(formulario.get("credito_dias"))
    elif opcion == credito.DIA_FIJO:
        tipo, valor = credito.DIA_FIJO, entero(formulario.get("credito_dia"))
    elif opcion == credito.FIN_MES:
        tipo, valor = credito.FIN_MES, None
    else:
        tipo, valor = None, None
    notas = str(formulario.get("notas") or "").strip() or None
    return {
        "nombre": servicios.limpiar(formulario.get("nombre")),
        "tipo_id_id": entero(formulario.get("tipo_id_id")),
        "numero_id": servicios.sin_espacios(formulario.get("numero_id")),
        "tipo_cuenta_id": entero(formulario.get("tipo_cuenta_id")),
        "numero_cuenta": servicios.sin_espacios(formulario.get("numero_cuenta")),
        "banco_id": entero(formulario.get("banco_id")),
        "correo": servicios.limpiar(formulario.get("correo")),
        "credito_tipo": tipo,
        "credito_valor": valor,
        "registrado_banco": formulario.get("registrado_banco") == "1",
        "notas": notas,
    }


def _opcion_credito(datos: dict) -> str:
    if datos.get("credito_tipo") == credito.DIAS and not datos.get("credito_valor"):
        return "contado" if datos.get("credito_valor") == 0 else credito.DIAS
    return datos.get("credito_tipo") or ""


def _datos_de(p: Proveedor) -> dict:
    return {
        "nombre": p.nombre,
        "tipo_id_id": p.tipo_id_id,
        "numero_id": p.numero_id,
        "tipo_cuenta_id": p.tipo_cuenta_id,
        "numero_cuenta": p.numero_cuenta,
        "banco_id": p.banco_id,
        "correo": p.correo,
        "credito_tipo": p.credito_tipo,
        "credito_valor": p.credito_valor,
        "registrado_banco": p.registrado_banco,
        "notas": p.notas,
    }


def _formulario(request: Request, sesion: Session, datos: dict, p: Proveedor = None, errores=None, status_code=200):
    return render(
        request,
        "proveedor_form.html",
        status_code=status_code,
        p=p,
        datos=datos,
        opcion_credito=_opcion_credito(datos),
        errores=errores or [],
        **_opciones(sesion, p),
    )


@router.get("/proveedores")
def listado(
    request: Request,
    q: str = "",
    banco: str = "",
    aprobacion: str = "",
    estado: str = "activos",
    registrado: str = "",
    u: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(get_db),
):
    proveedores = _filtrar(sesion, q, banco, aprobacion, estado, registrado)
    filtros = {"q": q, "banco": banco, "aprobacion": aprobacion, "estado": estado, "registrado": registrado}
    if es_htmx(request):
        return render(request, "_proveedores_tabla.html", proveedores=proveedores)
    bancos_usados = sesion.scalars(
        select(Banco).where(Banco.id.in_(select(Proveedor.banco_id).where(Proveedor.banco_id.is_not(None)))).order_by(Banco.nombre)
    ).all()
    return render(request, "proveedores.html", proveedores=proveedores, filtros=filtros, bancos_usados=bancos_usados)


@router.get("/proveedores/exportar")
def exportar(
    q: str = "",
    banco: str = "",
    aprobacion: str = "",
    estado: str = "activos",
    registrado: str = "",
    u: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(get_db),
):
    proveedores = _filtrar(sesion, q, banco, aprobacion, estado, registrado)
    contenido = exportacion.a_bytes(exportacion.libro_proveedores(proveedores))
    nombre = f"proveedores-{config.ahora():%Y%m%d-%H%M}.xlsx"
    return Response(contenido, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.get("/proveedores/nuevo")
def pantalla_nuevo(request: Request, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    return _formulario(request, sesion, {"registrado_banco": False})


@router.post("/proveedores/nuevo")
async def crear(request: Request, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    datos = _datos_formulario(await request.form())
    errores = servicios.validar_datos(sesion, datos)
    if errores:
        return _formulario(request, sesion, datos, errores=errores, status_code=400)
    p = servicios.crear_proveedor(sesion, datos, u)
    sesion.commit()
    aviso(request, "Proveedor creado. Queda pendiente hasta que otra persona lo apruebe.")
    return ir(f"/proveedores/{p.id}")


@router.get("/proveedores/{pid}")
def ficha(request: Request, pid: int, u: Usuario = Depends(usuario_actual), sesion: Session = Depends(get_db)):
    p = _proveedor(sesion, pid)
    historial = sesion.scalars(
        select(Historial).where(Historial.proveedor_id == p.id).order_by(Historial.fecha.desc(), Historial.id.desc()).limit(300)
    ).all()
    facturas = sesion.scalars(
        select(Factura).where(Factura.proveedor_id == p.id).order_by(Factura.vencimiento.desc(), Factura.id.desc()).limit(200)
    ).all()
    return render(
        request,
        "proveedor_ficha.html",
        p=p,
        historial=historial,
        facturas=facturas,
        avisos=validaciones.avisos_de(sesion, p),
        bloqueo_aprobar=servicios.motivo_no_puede_aprobar(p, u),
    )


@router.get("/proveedores/{pid}/editar")
def pantalla_editar(request: Request, pid: int, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    p = _proveedor(sesion, pid)
    return _formulario(request, sesion, _datos_de(p), p=p)


@router.post("/proveedores/{pid}/editar")
async def editar(request: Request, pid: int, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    p = _proveedor(sesion, pid)
    datos = _datos_formulario(await request.form())
    errores = servicios.validar_datos(sesion, datos, proveedor_id=p.id)
    if errores:
        return _formulario(request, sesion, datos, p=p, errores=errores, status_code=400)
    estado_antes = p.estado_aprobacion
    cambios = servicios.aplicar_cambios(sesion, p, datos, u)
    sesion.commit()
    if not cambios:
        aviso(request, "No había cambios que guardar.", "alerta")
    elif p.estado_aprobacion != estado_antes:
        aviso(request, "Cambios guardados. El proveedor vuelve a quedar pendiente de aprobación.", "alerta")
    else:
        aviso(request, "Cambios guardados.")
    return ir(f"/proveedores/{p.id}")


@router.post("/proveedores/{pid}/activo")
async def cambiar_activo(request: Request, pid: int, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    p = _proveedor(sesion, pid)
    formulario = await request.form()
    activar = formulario.get("activo") == "1"
    servicios.aplicar_cambios(sesion, p, {"activo": activar}, u)
    sesion.commit()
    aviso(request, "Proveedor reactivado." if activar else "Proveedor desactivado.")
    return ir(f"/proveedores/{p.id}")
