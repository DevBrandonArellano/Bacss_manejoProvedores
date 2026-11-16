"""Mejoras de uso: orden y páginas, avisos al llenar formularios, vista previa del vencimiento y pago en lote."""
from datetime import timedelta

from sqlalchemy import select

from app import config
from app.modelos import FACTURA_PAGADA, FACTURA_PENDIENTE, Factura, Proveedor
from test_web import _crear_proveedor, _en_base, _uno, equipo  # noqa: F401  (equipo es un fixture)
from ayudas import formulario_proveedor, publicar

HTMX = {"HX-Request": "true"}


def _factura(navegador, pid, numero, fecha=None, valor="100"):
    fecha = fecha or config.hoy()
    respuesta = publicar(
        navegador,
        "/facturas/nueva",
        {"proveedor_id": str(pid), "numero": numero, "fecha": fecha.isoformat(), "valor": valor, "moneda": "USD", "notas": ""},
    )
    assert respuesta.status_code == 303, respuesta.text


# ---------------------------------------------------------------- proveedores: orden y páginas


def test_listado_con_orden_y_paginas(equipo, ids_catalogo):
    creador = equipo["creador"]
    for i in range(55):
        _crear_proveedor(
            creador, ids_catalogo, nombre=f"EMPRESA {i:02d}", numero_id=f"179000{i:04d}001", numero_cuenta=f"{5000 + i}"
        )
    pagina1 = creador.get("/proveedores").text
    assert "Mostrando 1–50 de 55" in pagina1 and "Página 1 de 2" in pagina1
    assert "EMPRESA 00" in pagina1 and "EMPRESA 54" not in pagina1
    pagina2 = creador.get("/proveedores", params={"pagina": "2"}).text
    assert "Mostrando 51–55 de 55" in pagina2 and "EMPRESA 54" in pagina2 and "EMPRESA 00" not in pagina2
    # Orden descendente por nombre: el último queda primero.
    desc = creador.get("/proveedores", params={"orden": "nombre", "dir": "desc"}).text
    assert desc.index("EMPRESA 54") < desc.index("EMPRESA 05")
    # Una página fuera de rango o un orden desconocido no rompen nada.
    assert creador.get("/proveedores", params={"pagina": "999"}).status_code == 200
    assert creador.get("/proveedores", params={"orden": "x; drop table", "dir": "zzz"}).status_code == 200
    # La parcial de HTMX trae también la paginación y los encabezados ordenables.
    parcial = creador.get("/proveedores", params={"pagina": "2"}, headers=HTMX).text
    assert "<html" not in parcial and 'data-orden="nombre"' in parcial and "Página 2 de 2" in parcial


def test_listado_vacio_guia_al_primer_proveedor(equipo):
    texto = equipo["creador"].get("/proveedores").text
    assert "Aún no hay proveedores" in texto and "Registrar el primer proveedor" in texto
    # El aprobador ve el aviso, pero no el botón de registrar.
    texto = equipo["aprobador"].get("/proveedores").text
    assert "Aún no hay proveedores" in texto and "Registrar el primer proveedor" not in texto


# ---------------------------------------------------------------- formulario de proveedor


def test_aviso_de_identificacion_y_cuenta_repetidas(equipo, ids_catalogo):
    creador = equipo["creador"]
    pid = _crear_proveedor(creador, ids_catalogo)
    base = {"tipo_id_id": str(ids_catalogo["tipo_id"]), "numero_id": "0190000000001", "numero_cuenta": "0009876543"}
    texto = creador.get("/proveedores/verificar", params=base, headers=HTMX).text
    assert "Ya existe un proveedor con ese" in texto and "ya lo tiene otro proveedor" in texto
    assert f"/proveedores/{pid}" in texto
    # Editando el mismo proveedor no se avisa contra sí mismo.
    propio = creador.get("/proveedores/verificar", params={**base, "pid": str(pid)}, headers=HTMX).text
    assert "Ya existe" not in propio and "ya lo tiene" not in propio
    # Datos nuevos: sin avisos.
    limpio = creador.get(
        "/proveedores/verificar", params={**base, "numero_id": "0190000000002", "numero_cuenta": "111"}, headers=HTMX
    ).text
    assert "Ya existe" not in limpio and "ya lo tiene" not in limpio
    # Es una pantalla para quien edita.
    assert equipo["aprobador"].get("/proveedores/verificar", params=base, headers=HTMX).status_code == 403


def test_formulario_expone_largos_de_id_y_bancos_frecuentes(equipo, ids_catalogo):
    _crear_proveedor(equipo["creador"], ids_catalogo)
    texto = equipo["creador"].get("/proveedores/nuevo").text
    assert 'data-largo="13"' in texto and 'data-largo="10"' in texto
    assert 'data-buscar="Escriba el nombre del banco' in texto
    assert 'data-frecuente="1"' in texto
    assert 'data-mostrar-si="credito=dias"' in texto and 'data-mostrar-si="credito=dia_fijo"' in texto


def test_guardar_sin_los_campos_de_credito_ocultos(equipo, ids_catalogo):
    """El navegador no envía los campos ocultos (deshabilitados): el servidor lo acepta igual."""
    datos = formulario_proveedor(ids_catalogo, credito="fin_mes")
    datos.pop("credito_dias"), datos.pop("credito_dia")
    respuesta = publicar(equipo["creador"], "/proveedores/nuevo", datos)
    assert respuesta.status_code == 303
    assert _uno(select(Proveedor)).credito_tipo == "fin_mes"


# ---------------------------------------------------------------- facturas


def test_vista_previa_del_vencimiento(equipo, ids_catalogo):
    creador = equipo["creador"]
    pid = _crear_proveedor(creador, ids_catalogo)  # 15 días de crédito, pendiente de aprobar
    hoy = config.hoy()
    texto = creador.get(
        "/facturas/vencimiento", params={"proveedor_id": str(pid), "fecha": hoy.isoformat()}, headers=HTMX
    ).text
    esperado = (hoy + timedelta(days=15)).strftime("%d/%m/%Y")
    assert esperado in texto and "dentro de 15 días" in texto and "15 días" in texto
    assert "pendiente" in texto  # avisa que aún no se puede exportar
    pasado = creador.get(
        "/facturas/vencimiento", params={"proveedor_id": str(pid), "fecha": (hoy - timedelta(days=20)).isoformat()}, headers=HTMX
    ).text
    assert "ya vencida hace 5 días" in pasado
    # Sin datos suficientes, una guía; con datos inválidos, nunca un error.
    assert "Elija el proveedor" in creador.get("/facturas/vencimiento", headers=HTMX).text
    assert "Elija el proveedor" in creador.get(
        "/facturas/vencimiento", params={"proveedor_id": "abc", "fecha": "no-es-fecha"}, headers=HTMX
    ).text


def test_vista_previa_coincide_con_lo_que_se_guarda(equipo, ids_catalogo):
    creador = equipo["creador"]
    pid = _crear_proveedor(creador, ids_catalogo, credito="dia_fijo", credito_dia="29")
    fecha = config.hoy().replace(day=1)
    _factura(creador, pid, "F-PREVIA", fecha)
    guardada = _uno(select(Factura)).vencimiento
    texto = creador.get("/facturas/vencimiento", params={"proveedor_id": str(pid), "fecha": fecha.isoformat()}, headers=HTMX).text
    assert guardada.strftime("%d/%m/%Y") in texto


def test_guardar_y_registrar_otra_conserva_proveedor_y_fecha(equipo, ids_catalogo):
    creador = equipo["creador"]
    pid = _crear_proveedor(creador, ids_catalogo)
    fecha = config.hoy() - timedelta(days=3)
    respuesta = publicar(
        creador,
        "/facturas/nueva",
        {"proveedor_id": str(pid), "numero": "F-A", "fecha": fecha.isoformat(), "valor": "10", "moneda": "USD", "despues": "otra"},
    )
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"/facturas/nueva?proveedor={pid}&fecha={fecha.isoformat()}"
    formulario = creador.get(respuesta.headers["location"]).text
    assert f'value="{fecha.isoformat()}"' in formulario and f'<option value="{pid}" selected' in formulario
    # Sin ese botón, vuelve al listado como antes.
    normal = publicar(
        creador, "/facturas/nueva",
        {"proveedor_id": str(pid), "numero": "F-B", "fecha": fecha.isoformat(), "valor": "10", "moneda": "USD"},
    )
    assert normal.headers["location"] == "/facturas"


def test_pagar_varias_facturas_a_la_vez(equipo, ids_catalogo):
    creador, aprobador = equipo["creador"], equipo["aprobador"]
    pid = _crear_proveedor(creador, ids_catalogo)
    for numero in ("F-1", "F-2", "F-3"):
        _factura(creador, pid, numero)
    ids = [f.id for f in _en_base(select(Factura).order_by(Factura.id))]
    # Marca como pagada una de antemano para comprobar el mensaje de omitidas.
    assert publicar(creador, f"/facturas/{ids[2]}/pagar").status_code == 303
    respuesta = publicar(creador, "/facturas/pagar-lote", {"ids": [str(i) for i in ids]})
    assert respuesta.status_code == 303
    assert {f.estado for f in _en_base(select(Factura))} == {FACTURA_PAGADA}
    assert "2 facturas marcadas como pagadas. 1 no estaba pendiente y se omitió." in creador.get("/facturas").text
    # Sin selección: aviso, nada cambia. El aprobador no puede pagar.
    assert publicar(creador, "/facturas/pagar-lote", {}).status_code == 303
    assert "Seleccione al menos una factura" in creador.get("/facturas").text
    assert publicar(aprobador, "/facturas/pagar-lote", {"ids": [str(ids[0])]}).status_code == 403


def test_listado_de_facturas_tiene_barra_de_seleccion_y_datos_para_el_total(equipo, ids_catalogo):
    creador = equipo["creador"]
    assert "Aún no hay facturas" in creador.get("/facturas").text
    pid = _crear_proveedor(creador, ids_catalogo)
    _factura(creador, pid, "F-1", valor="1250.50")
    texto = creador.get("/facturas").text
    assert 'id="seleccion"' in texto and 'data-valor="125050"' in texto and 'data-moneda="USD"' in texto
    assert 'id="lista-facturas"' in texto
    # El aprobador mira pero no tiene la barra de acciones.
    assert 'id="seleccion"' not in equipo["aprobador"].get("/facturas").text
    # Un filtro sin resultados no muestra la guía de «primera vez».
    assert "Aún no hay facturas" not in creador.get("/facturas", params={"q": "zzz"}).text


# ---------------------------------------------------------------- panel, menú y avisos


def test_panel_oculta_tablas_vacias_y_enlaza_las_tarjetas(equipo, ids_catalogo):
    creador = equipo["creador"]
    assert "Todo al día" in creador.get("/").text
    pid = _crear_proveedor(creador, ids_catalogo)
    _factura(creador, pid, "F-HOY", config.hoy() - timedelta(days=15), valor="480.75")
    texto = creador.get("/").text
    assert "Todo al día" not in texto
    assert 'id="hoy"' in texto and 'id="vencidas"' not in texto and 'id="proximas"' not in texto
    assert 'href="#vencidas"' in texto and "USD 480.75" in texto


def test_menu_agrupado_por_perfil(equipo):
    admin = equipo["admin"].get("/").text
    assert "<summary>Administración</summary>" in admin and "<summary>Control</summary>" in admin
    assert 'href="/usuarios"' in admin and 'href="/catalogos"' in admin
    creador = equipo["creador"].get("/").text
    assert "<summary>Control</summary>" in creador and "<summary>Administración</summary>" not in creador
    assert 'href="/usuarios"' not in creador


def test_las_respuestas_parciales_no_gastan_los_avisos(equipo, ids_catalogo):
    creador = equipo["creador"]
    _crear_proveedor(creador, ids_catalogo)  # deja el aviso «Proveedor creado…» pendiente
    creador.get("/proveedores", params={"q": "x"}, headers=HTMX)  # búsqueda en vivo
    assert "Proveedor creado" in creador.get("/proveedores").text
