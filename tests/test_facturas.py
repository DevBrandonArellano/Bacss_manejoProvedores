"""Facturas: vencimiento según el crédito del proveedor, panel de alarmas y respaldos."""
import sqlite3
from datetime import date

import pytest

import ayudas
from app import servicios, tareas
from app.modelos import FACTURA_ANULADA, FACTURA_PAGADA, FACTURA_PENDIENTE
from app.servicios import ErrorNegocio


@pytest.mark.parametrize(
    "texto, centavos",
    [("1250.50", 125050), ("1250,50", 125050), ("1.250,50", 125050), ("1,250.50", 125050), ("10", 1000), (" 0.01 ", 1)],
)
def test_interpretar_valor(texto, centavos):
    assert servicios.interpretar_valor(texto) == centavos


@pytest.mark.parametrize("texto", ["", "abc", "0", "-5", "1.234", "NaN", "1e3000"])
def test_valores_invalidos(texto):
    with pytest.raises(ErrorNegocio):
        servicios.interpretar_valor(texto)


def test_el_vencimiento_sale_del_credito_del_proveedor(sesion, personas):
    creador, aprobador = personas["creador"], personas["aprobador"]
    treinta = ayudas.proveedor_aprobado(sesion, creador, aprobador)  # 30 días
    contado = ayudas.proveedor_aprobado(
        sesion, creador, aprobador, nombre="CONTADO", numero_id="0990000000002", credito_tipo="dias", credito_valor=0
    )
    fin_mes = ayudas.proveedor_aprobado(
        sesion, creador, aprobador, nombre="FIN DE MES", numero_id="0990000000003", credito_tipo="fin_mes", credito_valor=None
    )
    dia_29 = ayudas.proveedor_aprobado(
        sesion, creador, aprobador, nombre="DIA 29", numero_id="0990000000004", credito_tipo="dia_fijo", credito_valor=29
    )
    sin_credito = ayudas.proveedor_aprobado(
        sesion, creador, aprobador, nombre="SIN CREDITO", numero_id="0990000000005", credito_tipo=None, credito_valor=None
    )
    fecha = date(2026, 2, 10)

    assert ayudas.factura(sesion, treinta, creador, fecha=fecha).vencimiento == date(2026, 3, 12)
    assert ayudas.factura(sesion, contado, creador, fecha=fecha).vencimiento == date(2026, 2, 10)
    assert ayudas.factura(sesion, fin_mes, creador, fecha=fecha).vencimiento == date(2026, 2, 28)
    assert ayudas.factura(sesion, dia_29, creador, fecha=fecha).vencimiento == date(2026, 2, 28)
    assert ayudas.factura(sesion, sin_credito, creador, fecha=fecha).vencimiento == date(2026, 2, 10)


def test_factura_repetida_o_incompleta(sesion, personas):
    p = ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    ayudas.factura(sesion, p, personas["creador"], numero="F-1")
    with pytest.raises(ErrorNegocio, match="ya tiene"):
        ayudas.factura(sesion, p, personas["creador"], numero="F-1")
    with pytest.raises(ErrorNegocio, match="obligatorio"):
        ayudas.factura(sesion, p, personas["creador"], numero="  ")
    with pytest.raises(ErrorNegocio, match="moneda"):
        servicios.crear_factura(sesion, p, "F-2", date(2026, 3, 1), 100, "DOLAR", personas["creador"])
    servicios.aplicar_cambios(sesion, p, {"activo": False}, personas["creador"])
    with pytest.raises(ErrorNegocio, match="desactivado"):
        ayudas.factura(sesion, p, personas["creador"], numero="F-3")


def test_panel_agrupa_vencidas_hoy_y_proximas(sesion, personas):
    creador = personas["creador"]
    p = ayudas.proveedor_aprobado(sesion, creador, personas["aprobador"], credito_tipo="dias", credito_valor=0)
    hoy = date(2026, 3, 15)
    vencida = ayudas.factura(sesion, p, creador, numero="VENCIDA", fecha=date(2026, 3, 1))
    de_hoy = ayudas.factura(sesion, p, creador, numero="HOY", fecha=hoy)
    proxima = ayudas.factura(sesion, p, creador, numero="PROXIMA", fecha=date(2026, 3, 22))  # justo en el límite de 7 días
    lejana = ayudas.factura(sesion, p, creador, numero="LEJANA", fecha=date(2026, 3, 23))
    pagada = ayudas.factura(sesion, p, creador, numero="PAGADA", fecha=date(2026, 3, 2))
    servicios.marcar_pagada(sesion, pagada, creador, hoy)
    sesion.commit()

    grupos = servicios.facturas_por_vencer(sesion, hoy, 7)

    assert [f.numero for f in grupos["vencidas"]] == ["VENCIDA"]
    assert [f.numero for f in grupos["hoy"]] == ["HOY"]
    assert [f.numero for f in grupos["proximas"]] == ["PROXIMA"]
    assert lejana.numero not in {f.numero for lista in grupos.values() for f in lista}

    # con más días de aviso entra la lejana
    assert [f.numero for f in servicios.facturas_por_vencer(sesion, hoy, 8)["proximas"]] == ["PROXIMA", "LEJANA"]
    assert vencida.estado == de_hoy.estado == proxima.estado == FACTURA_PENDIENTE


def test_una_factura_aparece_en_el_panel_el_dia_que_corresponde(sesion, personas):
    creador = personas["creador"]
    p = ayudas.proveedor_aprobado(sesion, creador, personas["aprobador"])  # 30 días
    f = ayudas.factura(sesion, p, creador, fecha=date(2026, 3, 10))  # vence el 9 de abril
    assert f.vencimiento == date(2026, 4, 9)

    def donde(dia):
        grupos = servicios.facturas_por_vencer(sesion, dia, 7)
        return [clave for clave, lista in grupos.items() if f in lista]

    assert donde(date(2026, 4, 1)) == []  # faltan 8 días: todavía no avisa
    assert donde(date(2026, 4, 2)) == ["proximas"]  # faltan 7
    assert donde(date(2026, 4, 9)) == ["hoy"]
    assert donde(date(2026, 4, 10)) == ["vencidas"]


def test_no_se_reabre_una_anulada_si_hay_otra_con_el_mismo_numero(sesion, personas):
    creador = personas["creador"]
    p = ayudas.proveedor_aprobado(sesion, creador, personas["aprobador"])
    vieja = ayudas.factura(sesion, p, creador, numero="F-1")
    servicios.anular_factura(sesion, vieja)
    sesion.commit()  # como la ruta; la sesión no hace autoflush
    ayudas.factura(sesion, p, creador, numero="F-1")
    with pytest.raises(ErrorNegocio, match="otra factura"):
        servicios.reabrir_factura(sesion, vieja)
    assert vieja.estado == FACTURA_ANULADA


def test_pagar_reabrir_y_anular(sesion, personas):
    creador = personas["creador"]
    p = ayudas.proveedor_aprobado(sesion, creador, personas["aprobador"])
    f = ayudas.factura(sesion, p, creador)

    servicios.marcar_pagada(sesion, f, creador, date(2026, 3, 20))
    assert (f.estado, f.pagada_en, f.pagada_por_id) == (FACTURA_PAGADA, date(2026, 3, 20), creador.id)
    with pytest.raises(ErrorNegocio):
        servicios.marcar_pagada(sesion, f, creador)

    servicios.reabrir_factura(sesion, f)
    assert (f.estado, f.pagada_en, f.pagada_por_id) == (FACTURA_PENDIENTE, None, None)

    servicios.anular_factura(sesion, f)
    assert f.estado == FACTURA_ANULADA
    sesion.commit()
    assert servicios.facturas_por_vencer(sesion, date(2030, 1, 1), 7)["vencidas"] == []


def test_totales_por_moneda(sesion, personas):
    creador = personas["creador"]
    p = ayudas.proveedor_aprobado(sesion, creador, personas["aprobador"])
    a = ayudas.factura(sesion, p, creador, numero="A", valor="1000.25")
    b = ayudas.factura(sesion, p, creador, numero="B", valor="250.25")
    assert servicios.totales([a, b]) == "USD 1,250.50"
    assert servicios.totales([]) == ""


# ---------------------------------------------------------------- respaldos y tarea diaria


def test_respaldo_es_una_copia_legible_de_la_base(sesion, personas, entorno):
    ayudas.proveedor_aprobado(sesion, personas["creador"], personas["aprobador"])
    destino = tareas.respaldar()

    assert destino.parent == entorno.ruta_respaldos
    assert tareas.PATRON_RESPALDO.match(destino.name)
    copia = sqlite3.connect(str(destino))
    try:
        assert copia.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0] == 1
        assert copia.execute("SELECT numero_cuenta FROM proveedores").fetchone()[0] == "0012345678"
    finally:
        copia.close()


def test_se_conservan_solo_los_ultimos_30_respaldos(sesion, entorno):
    carpeta = entorno.ruta_respaldos
    carpeta.mkdir(parents=True)
    for dia in range(1, 36):  # 35 respaldos antiguos
        (carpeta / f"proveedores-2020{(dia - 1) // 28 + 1:02d}{(dia - 1) % 28 + 1:02d}-070000.db").write_bytes(b"viejo")
    (carpeta / "no-es-un-respaldo.txt").write_text("no se toca", encoding="utf-8")

    nuevo = tareas.respaldar()

    respaldos = tareas.listar_respaldos(carpeta)
    assert len(respaldos) == 30
    assert respaldos[0] == nuevo, "el respaldo más reciente se conserva"
    nombres = {r.name for r in respaldos}
    assert "proveedores-20200101-070000.db" not in nombres, "se borran los más antiguos"
    assert "proveedores-20200207-070000.db" in nombres
    assert (carpeta / "no-es-un-respaldo.txt").exists()


def test_revision_diaria_cuenta_y_no_envia_correo_por_defecto(sesion, personas, monkeypatch):
    creador = personas["creador"]
    p = ayudas.proveedor_aprobado(sesion, creador, personas["aprobador"], credito_tipo="dias", credito_valor=0)
    ayudas.factura(sesion, p, creador, numero="VIEJA", fecha=date(2020, 1, 1))
    enviados = []
    monkeypatch.setattr(tareas, "enviar_correo", lambda asunto, cuerpo: enviados.append(asunto))

    conteo = tareas.revisar_alarmas()

    assert conteo["vencidas"] == 1
    assert enviados == [], "el envío por correo está apagado por defecto"
    sesion.expire_all()
    assert "correo enviado: no" in servicios.cfg_leer(sesion, "ultima_revision")


def test_revision_diaria_envia_correo_si_se_enciende(sesion, personas, entorno, monkeypatch):
    creador = personas["creador"]
    p = ayudas.proveedor_aprobado(sesion, creador, personas["aprobador"], credito_tipo="dias", credito_valor=0)
    ayudas.factura(sesion, p, creador, numero="VIEJA", fecha=date(2020, 1, 1))
    entorno.correo_activo = True
    entorno.smtp_host = "smtp.example"
    entorno.correo_destinatarios = ["pagos@empresa.example"]
    enviados = []
    monkeypatch.setattr(tareas, "enviar_correo", lambda asunto, cuerpo: enviados.append((asunto, cuerpo)))

    tareas.revisar_alarmas()

    assert len(enviados) == 1
    asunto, cuerpo = enviados[0]
    assert "1 vencidos" in asunto
    assert "VIEJA" in cuerpo and "FERRETERIA INVENTADA S.A." in cuerpo
