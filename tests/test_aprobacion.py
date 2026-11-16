"""Flujo de aprobación: quien crea no aprueba."""
import pytest
from sqlalchemy import select

import ayudas
from app import servicios
from app.modelos import APROBADO, PENDIENTE, RECHAZADO, Historial
from app.servicios import ErrorNegocio


def _nuevo(sesion, usuario, **cambios):
    p = servicios.crear_proveedor(sesion, ayudas.datos_proveedor(sesion, **cambios), usuario)
    sesion.commit()
    return p


def test_proveedor_nuevo_nace_pendiente(sesion, personas):
    p = _nuevo(sesion, personas["creador"])
    assert p.estado_aprobacion == PENDIENTE
    assert servicios.contar_pendientes(sesion) == 1


def test_el_aprobador_aprueba(sesion, personas):
    p = _nuevo(sesion, personas["creador"])
    servicios.aprobar(sesion, p, personas["aprobador"])
    sesion.commit()

    assert p.estado_aprobacion == APROBADO
    assert p.aprobado_por_id == personas["aprobador"].id
    assert p.aprobado_en is not None
    assert servicios.contar_pendientes(sesion) == 0
    decision = sesion.scalars(select(Historial).where(Historial.proveedor_id == p.id, Historial.tipo == "aprobacion")).one()
    assert decision.usuario_id == personas["aprobador"].id
    assert decision.valor_nuevo == "Aprobado"


def test_el_creador_no_puede_aprobar(sesion, personas):
    p = _nuevo(sesion, personas["creador"])
    with pytest.raises(ErrorNegocio):
        servicios.aprobar(sesion, p, personas["creador"])
    with pytest.raises(ErrorNegocio):
        servicios.rechazar(sesion, p, personas["creador"], "motivo")
    assert p.estado_aprobacion == PENDIENTE


def test_el_administrador_no_aprueba_lo_que_el_mismo_creo(sesion, personas):
    p = _nuevo(sesion, personas["admin"])
    with pytest.raises(ErrorNegocio, match="usted mismo creó"):
        servicios.aprobar(sesion, p, personas["admin"])
    servicios.aprobar(sesion, p, personas["aprobador"])
    assert p.estado_aprobacion == APROBADO


def test_el_administrador_si_aprueba_lo_de_otro(sesion, personas):
    p = _nuevo(sesion, personas["creador"])
    servicios.aprobar(sesion, p, personas["admin"])
    assert p.estado_aprobacion == APROBADO


def test_nadie_aprueba_su_propia_modificacion(sesion, personas):
    p = _nuevo(sesion, personas["creador"])
    servicios.aprobar(sesion, p, personas["aprobador"])
    servicios.aplicar_cambios(sesion, p, {"numero_cuenta": "0077777777"}, personas["admin"])
    sesion.commit()
    assert p.estado_aprobacion == PENDIENTE

    with pytest.raises(ErrorNegocio, match="última modificación"):
        servicios.aprobar(sesion, p, personas["admin"])
    with pytest.raises(ErrorNegocio, match="usted mismo creó"):
        servicios.aprobar(sesion, p, personas["creador"])
    servicios.aprobar(sesion, p, personas["aprobador"])
    assert p.estado_aprobacion == APROBADO


def test_rechazar_exige_motivo(sesion, personas):
    p = _nuevo(sesion, personas["creador"])
    with pytest.raises(ErrorNegocio, match="motivo"):
        servicios.rechazar(sesion, p, personas["aprobador"], "   ")
    assert p.estado_aprobacion == PENDIENTE

    servicios.rechazar(sesion, p, personas["aprobador"], "El RUC no corresponde al nombre")
    sesion.commit()
    assert p.estado_aprobacion == RECHAZADO
    assert p.motivo_rechazo == "El RUC no corresponde al nombre"
    rechazo = sesion.scalars(select(Historial).where(Historial.proveedor_id == p.id, Historial.tipo == "rechazo")).one()
    assert "El RUC no corresponde al nombre" in rechazo.valor_nuevo


def test_no_se_aprueba_dos_veces(sesion, personas):
    p = _nuevo(sesion, personas["creador"])
    servicios.aprobar(sesion, p, personas["aprobador"])
    with pytest.raises(ErrorNegocio, match="no está pendiente"):
        servicios.aprobar(sesion, p, personas["aprobador"])


def test_el_aprobador_ve_que_cambio_desde_la_ultima_aprobacion(sesion, personas):
    p = _nuevo(sesion, personas["creador"])
    nuevos = servicios.cambios_por_revisar(sesion, p)
    assert [h.tipo for h in nuevos] == ["creacion"]

    servicios.aprobar(sesion, p, personas["aprobador"])
    sesion.commit()
    servicios.aplicar_cambios(sesion, p, {"numero_cuenta": "0077777777", "correo": "otro@ferreteria-inventada.example"}, personas["creador"])
    sesion.commit()

    cambios = servicios.cambios_por_revisar(sesion, p)
    assert {h.campo for h in cambios} == {"Número de cuenta", "Correo"}
    cuenta = next(h for h in cambios if h.campo == "Número de cuenta")
    assert (cuenta.valor_anterior, cuenta.valor_nuevo) == ("0012345678", "0077777777")
