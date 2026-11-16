"""Preparación común: cada prueba usa su propia base de datos temporal. Nunca se toca la base real."""
import pytest

import ayudas


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("RUTA_BD", str(tmp_path / "prueba.db"))
    monkeypatch.setenv("RUTA_RESPALDOS", str(tmp_path / "respaldos"))
    monkeypatch.setenv("RUTA_EXCEL", str(tmp_path / "no-existe.xlsx"))
    monkeypatch.setenv("ADMIN_USUARIO", "admin")
    monkeypatch.setenv("ADMIN_CLAVE", ayudas.CLAVE_ADMIN)
    monkeypatch.setenv("ADMIN_NOMBRE", "Admin de Prueba")
    monkeypatch.setenv("CLAVE_SESION", "clave-de-sesion-solo-para-pruebas-0123456789")
    monkeypatch.setenv("COOKIE_SEGURA", "false")
    monkeypatch.setenv("TAREAS_ACTIVAS", "false")
    monkeypatch.setenv("FACTURACION_ACTIVA", "true")
    monkeypatch.setenv("CORREO_ACTIVO", "false")
    monkeypatch.setenv("RESPALDOS_CONSERVAR", "30")
    monkeypatch.setenv("ZONA_HORARIA", "America/Guayaquil")

    from app import config, seguridad

    seguridad.limpiar_fallos()
    return config.cargar()


@pytest.fixture
def sesion(entorno):
    """Sesión de base de datos con catálogos y administrador ya sembrados."""
    from app import catalogos, db

    db.iniciar_bd(entorno.ruta_bd)
    s = db.SessionLocal()
    catalogos.preparar_bd(s)
    try:
        yield s
    finally:
        s.close()
        db.cerrar_bd()


@pytest.fixture
def personas(sesion):
    """Los tres perfiles: administrador (sembrado), creador y aprobador."""
    from sqlalchemy import select

    from app.modelos import APROBADOR, CREADOR, Usuario

    return {
        "admin": sesion.scalars(select(Usuario).where(Usuario.usuario == "admin")).one(),
        "creador": ayudas.crear_usuario(sesion, "creador", CREADOR),
        "aprobador": ayudas.crear_usuario(sesion, "aprobador", APROBADOR),
    }


@pytest.fixture
def aplicacion(entorno):
    """La app arrancada (con su base temporal) y un cliente sin sesión."""
    from fastapi.testclient import TestClient

    from app.main import crear_app

    app = crear_app()
    with TestClient(app) as cliente:
        yield app, cliente


@pytest.fixture
def cliente(aplicacion):
    return aplicacion[1]


@pytest.fixture
def otro_cliente(aplicacion):
    """Fábrica de clientes adicionales (otro navegador, otra sesión) sobre la misma app."""
    from fastapi.testclient import TestClient

    def fabrica():
        return TestClient(aplicacion[0])

    return fabrica


@pytest.fixture
def ids_catalogo(aplicacion):
    """Ids de catálogo para llenar el formulario web de proveedor."""
    from app import db

    with db.SessionLocal() as s:
        return {
            "tipo_id": ayudas.tipo_id(s, "R").id,
            "tipo_cuenta": ayudas.tipo_cuenta(s, "AHO").id,
            "banco": ayudas.banco_de_prueba(s).id,
        }
