"""Lo que ve el revisor: una columna de crédito por empresa en el listado, la revisión y la exportación."""
import io

import openpyxl

from ayudas import publicar
from test_proveedor_empresas import _empresa_id
from test_web import _crear_proveedor, equipo  # noqa: F401


def _dos_creditos(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo, credito="contado")
    publicar(equipo["creador2"], f"/proveedores/{pid}/credito", {
        "empresa_id": str(_empresa_id("EMPRESA B")), "credito": "dias", "credito_dias": "15"})
    return pid


def test_el_revisor_ve_una_columna_por_empresa(equipo, ids_catalogo):
    _dos_creditos(equipo, ids_catalogo)
    texto = equipo["aprobador"].get("/proveedores").text
    for esperado in ("EMPRESA A", "EMPRESA B", "Contado", "15 días"):
        assert esperado in texto
    solo_a = equipo["creador"].get("/proveedores").text
    assert "EMPRESA A" in solo_a and "EMPRESA B" not in solo_a and "15 días" not in solo_a


def test_la_tarjeta_de_revision_muestra_los_creditos(equipo, ids_catalogo):
    _dos_creditos(equipo, ids_catalogo)
    texto = equipo["aprobador"].get("/aprobaciones").text
    # Una línea «empresa: crédito» por empresa (no basta con que salga en los cambios por revisar).
    assert "EMPRESA A: Contado" in texto and "EMPRESA B: 15 días" in texto


def test_empresa_desactivada_oculta_la_columna_y_conserva_los_creditos(equipo, ids_catalogo):
    _dos_creditos(equipo, ids_catalogo)
    b = _empresa_id("EMPRESA B")
    publicar(equipo["admin"], f"/empresas/{b}", {"nombre": "EMPRESA B"})  # desactiva
    assert "EMPRESA B" not in equipo["aprobador"].get("/proveedores").text
    publicar(equipo["admin"], f"/empresas/{b}", {"nombre": "EMPRESA B", "activo": "1"})
    assert "15 días" in equipo["aprobador"].get("/proveedores").text


def test_sin_empresas_creadas_nada_se_rompe(cliente, ids_catalogo):
    from ayudas import CLAVE_ADMIN, entrar
    entrar(cliente, "admin", CLAVE_ADMIN)
    for ruta in ("/proveedores", "/proveedores/nuevo", "/aprobaciones", "/validaciones"):
        assert cliente.get(ruta).status_code == 200
    assert cliente.get("/proveedores/exportar").status_code == 200


def test_exportar_proveedores_con_una_columna_por_empresa(equipo, ids_catalogo):
    _dos_creditos(equipo, ids_catalogo)
    contenido = equipo["aprobador"].get("/proveedores/exportar").content
    hoja = openpyxl.load_workbook(io.BytesIO(contenido)).active
    filas = list(hoja.iter_rows(values_only=True))
    encabezado, datos = filas[0], dict(zip(filas[0], filas[1]))
    assert "CREDITO EMPRESA A" in encabezado and "CREDITO EMPRESA B" in encabezado
    assert "DIAS CREDITO" not in encabezado
    assert (datos["CREDITO EMPRESA A"], datos["CREDITO EMPRESA B"]) == ("CONTADO", "15")


def test_sin_credito_significa_sin_ninguna_empresa(equipo, ids_catalogo):
    _crear_proveedor(equipo["creador"], ids_catalogo, credito="")
    assert "Sin crédito en ninguna empresa" in equipo["admin"].get("/validaciones").text
