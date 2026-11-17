"""Proveedores: listado, búsqueda, alta, edición, desactivación y exportación."""
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import config, credito, exportacion, identificacion, servicios, validaciones
from ..db import get_db
from ..modelos import CREADOR, ESTADOS_APROBACION, Banco, Empresa, Factura, Historial, Proveedor, TipoCuenta, TipoId, Usuario
from ..servicios import ErrorNegocio
from ..web import aviso, entero, es_htmx, ir, puede_editar, render, usuario_actual

router = APIRouter()

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _proveedor(sesion: Session, pid: int) -> Proveedor:
    p = sesion.get(Proveedor, pid)
    if p is None:
        raise HTTPException(status_code=404)
    return p


POR_PAGINA = 50
# Columnas por las que se puede ordenar el listado.
ORDENES = {
    "nombre": Proveedor.nombre_norm,
    "identificacion": Proveedor.numero_id,
    "banco": Banco.nombre_norm,
    "aprobacion": Proveedor.estado_aprobacion,
}


def _consulta(q: str, banco: str, aprobacion: str, estado: str, registrado: str, orden: str = "nombre", dir: str = "asc"):
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
    columna = ORDENES.get(orden, Proveedor.nombre_norm)
    # Los vacíos siempre al final; a igualdad, por nombre.
    return consulta.order_by(columna.is_(None), columna.desc() if dir == "desc" else columna, Proveedor.nombre_norm)


def _filtrar(sesion: Session, q: str, banco: str, aprobacion: str, estado: str, registrado: str, orden="nombre", dir="asc"):
    return sesion.scalars(_consulta(q, banco, aprobacion, estado, registrado, orden, dir)).all()


def _bancos_frecuentes(sesion: Session, limite: int = 8) -> set:
    """Ids de los bancos con más proveedores: se muestran primero en el buscador de bancos."""
    filas = sesion.execute(
        select(Proveedor.banco_id, func.count())
        .where(Proveedor.banco_id.is_not(None))
        .group_by(Proveedor.banco_id)
        .order_by(func.count().desc())
        .limit(limite)
    ).all()
    return {banco_id for banco_id, _ in filas}


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
        "bancos_frecuentes": _bancos_frecuentes(sesion),
        "largos_id": servicios.LARGO_ID,
    }


def _credito_de_formulario(formulario) -> Tuple[Optional[str], Optional[int]]:
    """(tipo, valor) a partir de los campos `credito`, `credito_dias` y `credito_dia`."""
    opcion = str(formulario.get("credito") or "")
    if opcion == "contado":
        return credito.DIAS, 0
    if opcion == credito.DIAS:
        return credito.DIAS, entero(formulario.get("credito_dias"))
    if opcion == credito.DIA_FIJO:
        return credito.DIA_FIJO, entero(formulario.get("credito_dia"))
    if opcion == credito.FIN_MES:
        return credito.FIN_MES, None
    return None, None


def _opcion_credito(tipo, valor) -> str:
    """Opción del desplegable de crédito que corresponde a (tipo, valor)."""
    if tipo == credito.DIAS and not valor:
        return "contado" if valor == 0 else credito.DIAS
    return tipo or ""


def _datos_formulario(formulario) -> dict:
    """Datos compartidos del proveedor. El crédito va aparte: es de cada empresa."""
    notas = str(formulario.get("notas") or "").strip() or None
    return {
        "nombre": servicios.limpiar(formulario.get("nombre")),
        "tipo_id_id": entero(formulario.get("tipo_id_id")),
        "numero_id": servicios.sin_espacios(formulario.get("numero_id")),
        "tipo_cuenta_id": entero(formulario.get("tipo_cuenta_id")),
        "numero_cuenta": servicios.sin_espacios(formulario.get("numero_cuenta")),
        "banco_id": entero(formulario.get("banco_id")),
        "correo": servicios.limpiar(formulario.get("correo")),
        "registrado_banco": formulario.get("registrado_banco") == "1",
        "notas": notas,
    }


def _datos_de(p: Proveedor) -> dict:
    return {
        "nombre": p.nombre,
        "tipo_id_id": p.tipo_id_id,
        "numero_id": p.numero_id,
        "tipo_cuenta_id": p.tipo_cuenta_id,
        "numero_cuenta": p.numero_cuenta,
        "banco_id": p.banco_id,
        "correo": p.correo,
        "registrado_banco": p.registrado_banco,
        "notas": p.notas,
    }


def _formulario(
    request: Request, sesion: Session, datos: dict, p: Proveedor = None, errores=None, status_code=200,
    credito_alta=(None, None),
):
    """Formulario de alta (con el crédito de la empresa del creador) o de edición (sin crédito)."""
    u = request.state.usuario
    return render(
        request,
        "proveedor_form.html",
        status_code=status_code,
        p=p,
        datos=datos,
        empresa_credito=servicios.empresa_de(u) if (p is None and u.rol == CREADOR) else None,
        opcion_credito=_opcion_credito(*credito_alta),
        valor_credito=credito_alta[1],
        errores=errores or [],
        **_opciones(sesion, p),
    )


def _creador_sin_empresa(request: Request, u: Usuario) -> bool:
    """Un creador sin empresa activa no puede registrar proveedores; se le avisa."""
    if u.rol == CREADOR and servicios.empresa_de(u) is None:
        aviso(request, "Su usuario no tiene empresa asignada. Pídale al administrador que se la asigne.", "error")
        return True
    return False


def _avisar_si_el_ruc_es_dudoso(request: Request, sesion: Session, p: Proveedor) -> None:
    """RUC de sociedad que no pasa el verificador: ya se guardó; solo se advierte."""
    tipo = sesion.get(TipoId, p.tipo_id_id) if p.tipo_id_id else None
    if tipo is not None and p.numero_id and identificacion.revisar(tipo.codigo, p.numero_id).avisos:
        aviso(
            request,
            "Atención: el RUC no pasó la verificación del dígito verificador. Se guardó igual; confírmelo en el SRI. "
            "Queda marcado en «Validaciones».",
            "alerta",
        )


@router.get("/proveedores")
def listado(
    request: Request,
    q: str = "",
    banco: str = "",
    aprobacion: str = "",
    estado: str = "activos",
    registrado: str = "",
    orden: str = "nombre",
    dir: str = "asc",
    pagina: str = "1",
    u: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(get_db),
):
    orden = orden if orden in ORDENES else "nombre"
    dir = "desc" if dir == "desc" else "asc"
    consulta = _consulta(q, banco, aprobacion, estado, registrado, orden, dir)
    total = sesion.scalar(select(func.count()).select_from(consulta.subquery())) or 0
    paginas = max(1, -(-total // POR_PAGINA))
    actual = min(max(entero(pagina) or 1, 1), paginas)
    proveedores = sesion.scalars(
        consulta.options(selectinload(Proveedor.creditos)).offset((actual - 1) * POR_PAGINA).limit(POR_PAGINA)
    ).all()
    filtros = {
        "q": q, "banco": banco, "aprobacion": aprobacion, "estado": estado, "registrado": registrado,
        "orden": orden, "dir": dir,
    }
    contexto = {
        "proveedores": proveedores,
        "filtros": filtros,
        "total": total,
        "pagina": actual,
        "paginas": paginas,
        "desde": (actual - 1) * POR_PAGINA + 1 if total else 0,
        "hasta": min(actual * POR_PAGINA, total),
        "hay_proveedores": total > 0 or sesion.scalar(select(func.count(Proveedor.id))) > 0,
        "empresas_cols": servicios.empresas_visibles(sesion, u),
    }
    if es_htmx(request):
        return render(request, "_proveedores_tabla.html", **contexto)
    bancos_usados = sesion.scalars(
        select(Banco).where(Banco.id.in_(select(Proveedor.banco_id).where(Proveedor.banco_id.is_not(None)))).order_by(Banco.nombre)
    ).all()
    return render(request, "proveedores.html", bancos_usados=bancos_usados, **contexto)


@router.get("/proveedores/exportar")
def exportar(
    q: str = "",
    banco: str = "",
    aprobacion: str = "",
    estado: str = "activos",
    registrado: str = "",
    orden: str = "nombre",
    dir: str = "asc",
    u: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(get_db),
):
    proveedores = _filtrar(sesion, q, banco, aprobacion, estado, registrado, orden, dir)
    empresas = servicios.empresas_visibles(sesion, u)
    contenido = exportacion.a_bytes(exportacion.libro_proveedores(proveedores, empresas))
    nombre = f"proveedores-{config.ahora():%Y%m%d-%H%M}.xlsx"
    return Response(contenido, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.get("/proveedores/verificar")
def verificar(
    request: Request,
    tipo_id_id: str = "",
    numero_id: str = "",
    numero_cuenta: str = "",
    pid: str = "",
    u: Usuario = Depends(puede_editar),
    sesion: Session = Depends(get_db),
):
    """Avisos mientras se llena el formulario: identificación o cuenta que ya tiene otro proveedor."""
    otro = entero(pid)
    avisos = []
    tipo = sesion.get(TipoId, entero(tipo_id_id)) if entero(tipo_id_id) else None
    numero_id = servicios.sin_espacios(numero_id)
    if tipo is not None and numero_id:
        largo = servicios.LARGO_ID.get(tipo.codigo)
        if largo and numero_id.isdigit() and len(numero_id) == largo:  # el largo ya lo avisa la pantalla
            revision = identificacion.revisar(tipo.codigo, numero_id)
            avisos += [("error", texto, None) for texto in revision.errores]
            avisos += [("alerta", texto, None) for texto in revision.avisos]
        consulta = select(Proveedor).where(Proveedor.tipo_id_id == tipo.id, Proveedor.numero_id == numero_id)
        if otro is not None:
            consulta = consulta.where(Proveedor.id != otro)
        repetido = sesion.scalars(consulta).first()
        if repetido is not None and otro is None:
            # En el alta no es un error: al guardar se reconoce el proveedor y solo se añade el crédito.
            if u.rol == CREADOR:
                texto = (f"Ese {tipo.nombre} ya está registrado. Al guardar solo se añadirá el crédito de su empresa; "
                         "ábralo para ver o corregir los demás datos")
            else:
                texto = f"Ese {tipo.nombre} ya está registrado; ábralo para ver o corregir sus datos"
            avisos.append(("alerta", texto, repetido))
        elif repetido is not None:
            avisos.append(("error", f"Ya existe un proveedor con ese {tipo.nombre}", repetido))
    numero_cuenta = servicios.sin_espacios(numero_cuenta)
    if numero_cuenta:
        consulta = select(Proveedor).where(Proveedor.numero_cuenta == numero_cuenta)
        if otro is not None:
            consulta = consulta.where(Proveedor.id != otro)
        misma = sesion.scalars(consulta).first()
        if misma is not None:
            avisos.append(("alerta", "Ese número de cuenta ya lo tiene otro proveedor", misma))
    return render(request, "_verificacion.html", avisos=avisos)


@router.get("/proveedores/nuevo")
def pantalla_nuevo(request: Request, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    if _creador_sin_empresa(request, u):
        return ir("/proveedores")
    return _formulario(request, sesion, {"registrado_banco": False})


def _agregar_a_existente(request: Request, sesion: Session, p: Proveedor, u: Usuario, tipo, valor):
    """Alta de un proveedor que ya existe: no se toca ningún dato compartido, solo el crédito de la empresa del creador."""
    empresa = servicios.empresa_de(u) if u.rol == CREADOR else None
    if empresa is not None and tipo:
        try:
            servicios.guardar_credito(sesion, p, empresa, tipo, valor, u)  # siempre la empresa del usuario
        except ErrorNegocio as error:
            sesion.rollback()
            aviso(request, f"Ese proveedor ya estaba registrado, pero no se guardó el crédito: {error}", "error")
            return ir(f"/proveedores/{p.id}")
        sesion.commit()
        mensaje = ("Ese proveedor ya estaba registrado: se añadió el crédito de su empresa. "
                   "Los demás datos no se cambiaron; use Editar si hay que corregirlos.")
    else:
        mensaje = "Ese proveedor ya estaba registrado. No se cambió ningún dato; use Editar si hay que corregirlos."
    if not p.activo:
        mensaje += " Atención: el proveedor está desactivado."
    aviso(request, mensaje, "alerta")
    return ir(f"/proveedores/{p.id}")


@router.post("/proveedores/nuevo")
async def crear(request: Request, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    if _creador_sin_empresa(request, u):
        return ir("/proveedores")
    formulario = await request.form()
    datos = _datos_formulario(formulario)
    tipo, valor = _credito_de_formulario(formulario)
    existente = servicios.proveedor_por_id(sesion, datos["tipo_id_id"], datos["numero_id"])
    if existente is not None:
        return _agregar_a_existente(request, sesion, existente, u, tipo, valor)
    empresa = servicios.empresa_de(u) if u.rol == CREADOR else None
    errores = servicios.validar_datos(sesion, datos)
    error_credito = credito.validar(tipo, valor) if empresa is not None else None
    if error_credito:
        errores.append(error_credito)
    if errores:
        return _formulario(request, sesion, datos, errores=errores, status_code=400, credito_alta=(tipo, valor))
    p = servicios.crear_proveedor(sesion, datos, u)
    if empresa is not None and tipo:
        servicios.guardar_credito(sesion, p, empresa, tipo, valor, u)
    sesion.commit()
    aviso(request, "Proveedor creado. Queda pendiente hasta que otra persona lo revise.")
    _avisar_si_el_ruc_es_dudoso(request, sesion, p)
    return ir(f"/proveedores/{p.id}")


@router.get("/proveedores/{pid}")
def ficha(request: Request, pid: int, u: Usuario = Depends(usuario_actual), sesion: Session = Depends(get_db)):
    p = _proveedor(sesion, pid)
    consulta = select(Historial).where(Historial.proveedor_id == p.id)
    visible = servicios.condicion_historial_visible(u)
    if visible is not None:
        consulta = consulta.where(visible)
    historial = sesion.scalars(consulta.order_by(Historial.fecha.desc(), Historial.id.desc()).limit(300)).all()
    facturas = []
    if config.actual.facturacion_activa:
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
        creditos=_creditos_ficha(sesion, p, u),
        creador_sin_empresa=u.rol == CREADOR and servicios.empresa_de(u) is None,
    )


def _creditos_ficha(sesion: Session, p: Proveedor, u: Usuario) -> list:
    """Una fila por empresa que `u` puede ver: su crédito con `p` y si puede cambiarlo."""
    filas = []
    for e in servicios.empresas_visibles(sesion, u):
        fila = p.credito_de(e.id)
        tipo, valor = (fila.credito_tipo, fila.credito_valor) if fila is not None else (None, None)
        filas.append({
            "empresa": e,
            "texto": p.credito_texto_de(e.id),
            "opcion": _opcion_credito(tipo, valor),
            "valor": valor,
            "editable": servicios.puede_editar_credito(u, e.id),
        })
    return filas


@router.post("/proveedores/{pid}/credito")
async def guardar_credito(request: Request, pid: int, u: Usuario = Depends(puede_editar), sesion: Session = Depends(get_db)):
    p = _proveedor(sesion, pid)
    formulario = await request.form()
    empresa_id = entero(formulario.get("empresa_id"))
    if empresa_id is None or not servicios.puede_editar_credito(u, empresa_id):
        raise HTTPException(status_code=403)
    empresa = sesion.get(Empresa, empresa_id)
    if empresa is None:
        raise HTTPException(status_code=404)
    tipo, valor = _credito_de_formulario(formulario)
    try:
        cambio = servicios.guardar_credito(sesion, p, empresa, tipo, valor, u)
        sesion.commit()
        aviso(request, "Crédito guardado." if cambio else "No había cambios que guardar.", "ok" if cambio else "alerta")
    except ErrorNegocio as error:
        sesion.rollback()
        aviso(request, str(error), "error")
    return ir(f"/proveedores/{p.id}")


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
        aviso(request, "Cambios guardados. El proveedor vuelve a quedar pendiente de revisión.", "alerta")
    else:
        aviso(request, "Cambios guardados.")
    _avisar_si_el_ruc_es_dudoso(request, sesion, p)
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
