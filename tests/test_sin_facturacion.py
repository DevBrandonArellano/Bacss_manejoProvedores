"""Con FACTURACION_ACTIVA=false (el valor por defecto) la app solo maneja proveedores; el código de facturas sigue ahí."""
import pytest
from sqlalchemy import select

from app import config, tareas
from app.modelos import Proveedor
from test_web import _crear_proveedor, _uno, equipo  # noqa: F401  (equipo es un fixture)
from ayudas import publicar


@pytest.fixture
def sin_facturacion(entorno, monkeypatch):
    """Apaga el interruptor antes de que arranque la app (la fixture `equipo` se pide después)."""
    monkeypatch.setenv("FACTURACION_ACTIVA", "false")
    config.cargar()


def test_por_defecto_esta_apagada(monkeypatch):
    monkeypatch.delenv("FACTURACION_ACTIVA", raising=False)
    assert config.cargar().facturacion_activa is False
    monkeypatch.setenv("FACTURACION_ACTIVA", "true")
    assert config.cargar().facturacion_activa is True


@pytest.mark.parametrize("ruta", ["/facturas", "/facturas/nueva", "/facturas/vencimiento"])
def test_las_pantallas_de_facturas_no_existen(sin_facturacion, equipo, ruta):
    for quien in ("admin", "creador", "aprobador"):
        assert equipo[quien].get(ruta).status_code == 404, (quien, ruta)


@pytest.mark.parametrize(
    "ruta", ["/facturas/nueva", "/facturas/exportar", "/facturas/pagar-lote", "/facturas/1/pagar", "/configuracion/revisar-alarmas"]
)
def test_las_acciones_de_facturas_no_existen(sin_facturacion, equipo, ruta):
    assert publicar(equipo["admin"], ruta, {"ids": ["1"]}).status_code == 404


def test_configuracion_de_alarmas_no_se_puede_guardar(sin_facturacion, equipo):
    assert publicar(equipo["admin"], "/configuracion", {"dias_aviso": "5", "contrapartida": "1"}).status_code == 404


def test_el_inicio_es_la_lista_de_proveedores(sin_facturacion, equipo):
    for quien in ("admin", "creador", "aprobador"):
        respuesta = equipo[quien].get("/", follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/proveedores")


def test_el_menu_no_muestra_facturas_ni_panel(sin_facturacion, equipo):
    texto = equipo["admin"].get("/proveedores").text
    assert 'href="/facturas"' not in texto and ">Panel<" not in texto and ">Facturas<" not in texto
    assert 'href="/proveedores"' in texto and 'href="/aprobaciones"' in texto


def test_la_ficha_no_habla_de_facturas(sin_facturacion, equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    texto = equipo["creador"].get(f"/proveedores/{pid}").text
    assert "Pendiente de revisión." in texto
    assert "Registrar factura" not in texto and "<h2>Facturas</h2>" not in texto and "factura" not in texto.lower()
    assert "Historial de cambios" in texto and "Editar" in texto


def test_otras_pantallas_no_mencionan_facturas(sin_facturacion, equipo):
    assert "factura" not in equipo["admin"].get("/usuarios").text.lower()
    assert "factura" not in equipo["aprobador"].get("/aprobaciones").text.lower()
    configuracion = equipo["admin"].get("/configuracion").text
    assert "Alarmas y archivo de pago" not in configuracion and "Revisar alarmas ahora" not in configuracion
    assert "Respaldar ahora" in configuracion and "Respaldo de la base de datos" in configuracion


def test_el_trabajo_con_proveedores_sigue_igual(sin_facturacion, equipo, ids_catalogo):
    creador, aprobador = equipo["creador"], equipo["aprobador"]
    pid = _crear_proveedor(creador, ids_catalogo)
    assert publicar(aprobador, f"/aprobaciones/{pid}/aprobar").status_code == 303
    assert _uno(select(Proveedor)).estado_aprobacion == "aprobado"
    assert creador.get("/proveedores/exportar").status_code == 200
    assert creador.get("/validaciones").status_code == 200
    assert creador.get("/historial").status_code == 200


def test_la_tarea_diaria_no_revisa_alarmas(sin_facturacion, equipo):
    assert tareas.revisar_alarmas() is None
