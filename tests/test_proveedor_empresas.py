"""Alta que reconoce un proveedor ya registrado y crédito por empresa en la ficha."""
from sqlalchemy import select

from app import db
from app.modelos import Empresa, Proveedor, ProveedorCredito
from ayudas import formulario_proveedor, publicar
from test_web import _crear_proveedor, equipo  # noqa: F401


def _empresa_id(nombre):
    with db.SessionLocal() as s:
        return s.scalars(select(Empresa).where(Empresa.nombre == nombre)).one().id


def _creditos(pid):
    with db.SessionLocal() as s:
        filas = s.scalars(select(ProveedorCredito).where(ProveedorCredito.proveedor_id == pid)).all()
        return {f.empresa_id: (f.credito_tipo, f.credito_valor) for f in filas}


def test_el_creador_registra_con_el_credito_de_su_empresa(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo, credito="dias", credito_dias="15")
    assert _creditos(pid) == {_empresa_id("EMPRESA A"): ("dias", 15)}
    with db.SessionLocal() as s:
        assert s.get(Proveedor, pid).credito_tipo is None  # columna antigua intacta


def test_registrar_uno_existente_solo_agrega_el_credito(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo, credito="dias", credito_dias="15")
    r = publicar(equipo["creador2"], "/proveedores/nuevo", formulario_proveedor(
        ids_catalogo, nombre="OTRO NOMBRE", numero_cuenta="0000000001", credito="contado"))
    assert r.status_code == 303 and r.headers["location"] == f"/proveedores/{pid}"
    with db.SessionLocal() as s:
        assert len(s.scalars(select(Proveedor)).all()) == 1
        assert s.get(Proveedor, pid).nombre == "DISTRIBUIDORA FICTICIA CIA. LTDA."
        assert s.get(Proveedor, pid).numero_cuenta == "0009876543"
    assert _creditos(pid) == {_empresa_id("EMPRESA A"): ("dias", 15), _empresa_id("EMPRESA B"): ("dias", 0)}
    assert "ya estaba registrado" in equipo["creador2"].get(f"/proveedores/{pid}").text


def test_el_id_con_espacios_tambien_se_reconoce(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    r = publicar(equipo["creador2"], "/proveedores/nuevo",
                 formulario_proveedor(ids_catalogo, numero_id=" 0190 000000001 "))
    assert r.headers["location"] == f"/proveedores/{pid}"


def test_proveedor_desactivado_recibe_credito_sin_reactivarse(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    publicar(equipo["creador"], f"/proveedores/{pid}/activo", {"activo": "0"})
    r = publicar(equipo["creador2"], "/proveedores/nuevo", formulario_proveedor(ids_catalogo, credito="contado"))
    assert r.headers["location"] == f"/proveedores/{pid}"
    with db.SessionLocal() as s:
        assert s.get(Proveedor, pid).activo is False
    assert _empresa_id("EMPRESA B") in _creditos(pid)
    assert "desactivado" in equipo["creador2"].get(f"/proveedores/{pid}").text


def test_el_creador_no_puede_escribir_el_credito_de_otra_empresa(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    b = _empresa_id("EMPRESA B")
    r = publicar(equipo["creador"], f"/proveedores/{pid}/credito",
                 {"empresa_id": str(b), "credito": "contado"})
    assert r.status_code == 403 and b not in _creditos(pid)
    # En el alta, un empresa_id escondido se ignora: se usa siempre la empresa del usuario.
    r = publicar(equipo["creador"], "/proveedores/nuevo", formulario_proveedor(
        ids_catalogo, numero_id="0990000000001", empresa_id=str(b), credito="contado"))
    assert b not in _creditos(int(r.headers["location"].rsplit("/", 1)[1]))


def test_permisos_del_credito_en_la_ficha(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    a, b = _empresa_id("EMPRESA A"), _empresa_id("EMPRESA B")
    datos = {"empresa_id": str(a), "credito": "dias", "credito_dias": "45"}
    assert publicar(equipo["aprobador"], f"/proveedores/{pid}/credito", datos).status_code == 403
    assert publicar(equipo["creador"], f"/proveedores/{pid}/credito", datos).status_code == 303
    assert publicar(equipo["admin"], f"/proveedores/{pid}/credito",
                    {"empresa_id": str(b), "credito": "fin_mes"}).status_code == 303
    assert _creditos(pid) == {a: ("dias", 45), b: ("fin_mes", None)}


def test_el_creador_solo_ve_su_empresa_en_la_ficha(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo, credito="dias", credito_dias="15")
    publicar(equipo["admin"], f"/proveedores/{pid}/credito",
             {"empresa_id": str(_empresa_id("EMPRESA B")), "credito": "contado"})
    assert "EMPRESA B" not in equipo["creador"].get(f"/proveedores/{pid}").text
    assert "EMPRESA B" not in equipo["creador"].get("/historial").text  # tampoco en el historial
    assert "EMPRESA A" in equipo["creador"].get("/historial").text
    texto = equipo["aprobador"].get(f"/proveedores/{pid}").text
    assert "EMPRESA A" in texto and "EMPRESA B" in texto
    assert "EMPRESA B" in equipo["aprobador"].get("/historial").text


def test_editar_no_toca_el_credito(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo, credito="dias", credito_dias="15")
    r = publicar(equipo["creador"], f"/proveedores/{pid}/editar",
                 formulario_proveedor(ids_catalogo, correo="nuevo@ficticio.example"))
    assert r.status_code == 303
    assert _creditos(pid) == {_empresa_id("EMPRESA A"): ("dias", 15)}


def test_un_creador_sin_empresa_activa_no_registra(equipo, ids_catalogo):
    publicar(equipo["admin"], f"/empresas/{_empresa_id('EMPRESA A')}", {"nombre": "EMPRESA A"})  # desactiva
    r = equipo["creador"].get("/proveedores/nuevo", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/proveedores"
    assert "no tiene empresa asignada" in equipo["creador"].get("/proveedores").text
