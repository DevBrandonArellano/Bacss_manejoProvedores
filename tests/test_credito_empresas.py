"""Crédito por empresa: un proveedor, una condición de crédito por cada empresa."""
import pytest
from sqlalchemy import select

import ayudas
from app import servicios
from app.modelos import Historial
from app.servicios import ErrorNegocio


def _proveedor(sesion, personas):
    return ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])


def test_guardar_crear_actualizar_y_borrar(sesion, personas):
    p, a = _proveedor(sesion, personas), personas["creador"].empresa
    servicios.guardar_credito(sesion, p, a, "dias", 15, personas["creador"])
    assert p.credito_texto_de(a.id) == "15 días"
    servicios.guardar_credito(sesion, p, a, "dias", 0, personas["creador"])
    assert p.credito_texto_de(a.id) == "Contado"
    servicios.guardar_credito(sesion, p, a, None, None, personas["creador"])
    assert p.credito_de(a.id) is None and p.credito_texto_de(a.id) == "—"


def test_dos_empresas_un_proveedor(sesion, personas):
    p = _proveedor(sesion, personas)
    a, b = personas["creador"].empresa, ayudas.empresa(sesion, "EMPRESA B")
    ayudas.con_credito(sesion, p, a, personas["admin"], "dias", 0)
    ayudas.con_credito(sesion, p, b, personas["admin"], "dias", 15)
    assert (p.credito_texto_de(a.id), p.credito_texto_de(b.id)) == ("Contado", "15 días")
    assert p.credito_texto_de(ayudas.empresa(sesion, "EMPRESA C").id) == "—"


def test_guardar_credito_no_reabre_la_revision_y_queda_en_el_historial(sesion, personas):
    p, c = _proveedor(sesion, personas), personas["creador"]
    modificado = (p.modificado_por_id, p.modificado_en)
    servicios.guardar_credito(sesion, p, c.empresa, "dias", 30, c)
    sesion.commit()
    assert p.estado_aprobacion == "aprobado" and (p.modificado_por_id, p.modificado_en) == modificado
    h = sesion.scalars(select(Historial).order_by(Historial.id.desc())).first()
    assert (h.campo, h.valor_anterior, h.valor_nuevo, h.sensible) == (
        f"Crédito · {c.empresa.nombre}", "(vacío)", "30 días", False)


def test_permisos_por_empresa(sesion, personas):
    p, b = _proveedor(sesion, personas), ayudas.empresa(sesion, "EMPRESA B")
    with pytest.raises(ErrorNegocio, match="su empresa"):
        servicios.guardar_credito(sesion, p, b, "dias", 5, personas["creador"])
    with pytest.raises(ErrorNegocio):
        servicios.guardar_credito(sesion, p, personas["creador"].empresa, "dias", 5, personas["aprobador"])
    assert servicios.guardar_credito(sesion, p, b, "dias", 5, personas["admin"]) is True


def test_credito_invalido_y_empresa_inactiva(sesion, personas):
    p, c = _proveedor(sesion, personas), personas["creador"]
    with pytest.raises(ErrorNegocio, match="días de crédito"):
        servicios.guardar_credito(sesion, p, c.empresa, "dias", None, c)
    servicios.actualizar_empresa(sesion, c.empresa, c.empresa.nombre, False)
    with pytest.raises(ErrorNegocio):
        servicios.aplicar_credito(sesion, p, c.empresa, "dias", 5, personas["admin"])


def test_empresas_visibles(sesion, personas):
    b = ayudas.empresa(sesion, "EMPRESA B")
    nombres = lambda u: [e.nombre for e in servicios.empresas_visibles(sesion, u)]  # noqa: E731
    assert nombres(personas["admin"]) == nombres(personas["aprobador"]) == ["EMPRESA A", "EMPRESA B"]
    assert nombres(personas["creador"]) == ["EMPRESA A"]
    servicios.actualizar_empresa(sesion, b, b.nombre, False)
    assert nombres(personas["admin"]) == ["EMPRESA A"]


def test_proveedor_por_id(sesion, personas):
    p = _proveedor(sesion, personas)
    assert servicios.proveedor_por_id(sesion, p.tipo_id_id, p.numero_id).id == p.id
    assert servicios.proveedor_por_id(sesion, None, p.numero_id) is None
    assert servicios.proveedor_por_id(sesion, p.tipo_id_id, None) is None
