"""Funciones de apoyo para las pruebas. Todos los datos son inventados."""
import re
from datetime import date

from sqlalchemy import select

from app import servicios
from app.modelos import Banco, TipoCuenta, TipoId

CLAVE_ADMIN = "clave-admin-123"


def clave_de(usuario: str) -> str:
    return f"clave-{usuario}-123"


def tipo_id(sesion, codigo: str) -> TipoId:
    return sesion.scalars(select(TipoId).where(TipoId.codigo == codigo)).one()


def tipo_cuenta(sesion, codigo: str) -> TipoCuenta:
    return sesion.scalars(select(TipoCuenta).where(TipoCuenta.codigo == codigo)).one()


def banco_de_prueba(sesion, codigo: str = "0042", nombre: str = "BANCO INVENTADO DE PRUEBA") -> Banco:
    banco = sesion.scalars(select(Banco).where(Banco.codigo == codigo, Banco.nombre == nombre)).first()
    if banco is None:
        banco = Banco(codigo=codigo, nombre=nombre, nombre_norm=servicios.normalizar(nombre), activo=True)
        sesion.add(banco)
        sesion.commit()
    return banco


def datos_proveedor(sesion, **cambios) -> dict:
    """Datos válidos de un proveedor ficticio (RUC y cuenta con ceros a la izquierda)."""
    datos = {
        "nombre": "FERRETERIA INVENTADA S.A.",
        "tipo_id_id": tipo_id(sesion, "R").id,
        "numero_id": "0990000000001",
        "tipo_cuenta_id": tipo_cuenta(sesion, "CTE").id,
        "numero_cuenta": "0012345678",
        "banco_id": banco_de_prueba(sesion).id,
        "correo": "pagos@ferreteria-inventada.example",
        "credito_tipo": "dias",
        "credito_valor": 30,
        "registrado_banco": False,
        "notas": None,
    }
    datos.update(cambios)
    return datos


def crear_usuario(sesion, usuario: str, rol: str):
    u = servicios.crear_usuario(sesion, usuario, usuario.capitalize(), clave_de(usuario), rol)
    sesion.commit()
    return u


def proveedor_aprobado(sesion, creador, aprobador, **cambios):
    p = servicios.crear_proveedor(sesion, datos_proveedor(sesion, **cambios), creador)
    servicios.aprobar(sesion, p, aprobador)
    sesion.commit()
    return p


def factura(sesion, p, usuario, numero="001-001-000000123", fecha=date(2026, 3, 10), valor="1250.50"):
    f = servicios.crear_factura(sesion, p, numero, fecha, servicios.interpretar_valor(valor), "USD", usuario)
    sesion.commit()
    return f


# ---------------------------------------------------------------- HTTP


def token(cliente, ruta: str = "/mi-clave") -> str:
    """Token CSRF de la sesión, leído de un formulario de la app."""
    respuesta = cliente.get(ruta)
    encontrado = re.search(r'name="csrf_token" value="([^"]+)"', respuesta.text)
    assert encontrado, f"No se encontró el token CSRF en {ruta} (estado {respuesta.status_code})"
    return encontrado.group(1)


def entrar(cliente, usuario: str, clave: str) -> None:
    respuesta = cliente.post(
        "/login",
        data={"usuario": usuario, "clave": clave, "csrf_token": token(cliente, "/login")},
        follow_redirects=False,
    )
    assert respuesta.status_code == 303, respuesta.text
    assert respuesta.headers["location"] == "/"


def publicar(cliente, ruta: str, datos: dict = None, **opciones):
    """POST con el token CSRF de la sesión. No sigue redirecciones."""
    cuerpo = dict(datos or {})
    cuerpo["csrf_token"] = token(cliente)
    opciones.setdefault("follow_redirects", False)
    return cliente.post(ruta, data=cuerpo, **opciones)


def formulario_proveedor(sesion_o_ids: dict, **cambios) -> dict:
    """Campos del formulario web de proveedor, a partir de ids de catálogo ya conocidos."""
    campos = {
        "nombre": "DISTRIBUIDORA FICTICIA CIA. LTDA.",
        "tipo_id_id": str(sesion_o_ids["tipo_id"]),
        "numero_id": "0190000000001",
        "tipo_cuenta_id": str(sesion_o_ids["tipo_cuenta"]),
        "numero_cuenta": "0009876543",
        "banco_id": str(sesion_o_ids["banco"]),
        "correo": "cobros@distribuidora-ficticia.example",
        "credito": "dias",
        "credito_dias": "15",
        "credito_dia": "",
        "notas": "",
    }
    campos.update(cambios)
    return campos
