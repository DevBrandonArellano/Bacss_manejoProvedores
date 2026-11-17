"""Empresas y la empresa de cada creador."""
import pytest
from sqlalchemy import select

import ayudas
from app import db, servicios
from app.modelos import APROBADOR, CREADOR, Empresa, Usuario
from app.servicios import ErrorNegocio
from ayudas import publicar
from test_web import equipo  # noqa: F401


def test_crear_empresa_no_admite_vacia_ni_repetida(sesion):
    e = servicios.crear_empresa(sesion, "  Cía   Norte ")
    assert e.nombre == "Cía Norte"
    with pytest.raises(ErrorNegocio, match="Escriba el nombre"):
        servicios.crear_empresa(sesion, "   ")
    with pytest.raises(ErrorNegocio, match="Ya existe"):
        servicios.crear_empresa(sesion, "CIA NORTE")  # mayúsculas y acentos no distinguen


def test_un_creador_nuevo_exige_empresa_activa(sesion):
    inactiva = ayudas.empresa(sesion, "VIEJA")
    servicios.actualizar_empresa(sesion, inactiva, "VIEJA", False)
    for empresa_id in (None, inactiva.id):
        with pytest.raises(ErrorNegocio, match="empresa"):
            servicios.crear_usuario(sesion, "nuevo", "Nuevo", "clave-nuevo-123", CREADOR, empresa_id)
    u = servicios.crear_usuario(sesion, "revisor", "Revisor", "clave-revisor-123", APROBADOR, inactiva.id)
    assert u.empresa_id is None  # solo el creador guarda empresa


def test_empresa_de_solo_si_esta_activa(sesion):
    e = ayudas.empresa(sesion)
    u = ayudas.crear_usuario(sesion, "ana", CREADOR, e)
    assert servicios.empresa_de(u).id == e.id
    servicios.actualizar_empresa(sesion, e, e.nombre, False)
    assert servicios.empresa_de(u) is None


def test_pantalla_empresas_solo_para_el_administrador(equipo):
    assert equipo["admin"].get("/empresas").status_code == 200
    assert equipo["creador"].get("/empresas").status_code == 403
    assert equipo["aprobador"].get("/empresas").status_code == 403


def test_administrador_crea_renombra_y_desactiva_empresas(equipo):
    assert publicar(equipo["admin"], "/empresas/nueva", {"nombre": "EMPRESA C"}).status_code == 303
    assert "EMPRESA C" in equipo["admin"].get("/empresas").text
    with db.SessionLocal() as s:
        c = s.scalars(select(Empresa).where(Empresa.nombre == "EMPRESA C")).one()
    publicar(equipo["admin"], f"/empresas/{c.id}", {"nombre": "EMPRESA CE", "activo": "1"})
    publicar(equipo["admin"], f"/empresas/{c.id}", {"nombre": "EMPRESA CE"})  # sin «activo»: se desactiva
    with db.SessionLocal() as s:
        c = s.get(Empresa, c.id)
        assert (c.nombre, c.activo) == ("EMPRESA CE", False)


def test_usuarios_muestra_y_cambia_la_empresa(equipo):
    with db.SessionLocal() as s:
        b = s.scalars(select(Empresa).where(Empresa.nombre == "EMPRESA B")).one()
        carla = s.scalars(select(Usuario).where(Usuario.usuario == "carla")).one()
    assert "EMPRESA A" in equipo["admin"].get("/usuarios").text
    publicar(equipo["admin"], f"/usuarios/{carla.id}",
             {"nombre": "Carla", "rol": "creador", "activo": "1", "empresa_id": str(b.id)})
    with db.SessionLocal() as s:
        assert s.get(Usuario, carla.id).empresa_id == b.id
