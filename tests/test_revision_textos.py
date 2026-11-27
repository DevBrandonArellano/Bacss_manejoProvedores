"""«Aprobación» pasa a «Revisión» en todo lo que se ve en pantalla."""
import re

from ayudas import publicar
from test_web import _crear_proveedor, equipo  # noqa: F401

PROHIBIDO = re.compile(r"aprobaci|aprobad|aprobar|aprobador", re.I)


def _visible(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)  # quita etiquetas: href, class y action no cuentan


def test_ninguna_pantalla_habla_de_aprobacion(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    paginas = [
        ("creador", "/"), ("creador", "/proveedores"), ("creador", f"/proveedores/{pid}"),
        ("creador", "/proveedores/nuevo"), ("aprobador", f"/proveedores/{pid}"),
        ("aprobador", "/aprobaciones"), ("admin", "/aprobaciones"), ("admin", "/validaciones"),
        ("admin", "/historial"), ("admin", "/usuarios"), ("admin", "/facturas"),
    ]
    for quien, ruta in paginas:
        texto = _visible(equipo[quien].get(ruta).text)
        assert not PROHIBIDO.search(texto), (ruta, PROHIBIDO.search(texto).group())
    assert publicar(equipo["aprobador"], f"/aprobaciones/{pid}/aprobar").status_code == 303
    ficha = _visible(equipo["creador"].get(f"/proveedores/{pid}").text)
    assert "Revisado" in ficha and not PROHIBIDO.search(ficha)
