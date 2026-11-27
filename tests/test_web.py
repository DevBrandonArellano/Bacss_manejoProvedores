"""La app por HTTP: sesión, CSRF, permisos por perfil y el recorrido completo de dos personas."""
import io
from datetime import timedelta

import openpyxl
import pytest
from sqlalchemy import select

import ayudas
from app import config, db
from app.modelos import ADMINISTRADOR, APROBADO, FACTURA_PAGADA, PENDIENTE, Banco, Empresa, Factura, Proveedor, Usuario
from ayudas import CLAVE_ADMIN, clave_de, entrar, formulario_proveedor, publicar

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

RUTAS_PROTEGIDAS = [
    "/",
    "/proveedores",
    "/proveedores/nuevo",
    "/proveedores/exportar",
    "/proveedores/1",
    "/proveedores/1/editar",
    "/facturas",
    "/facturas/nueva",
    "/aprobaciones",
    "/validaciones",
    "/historial",
    "/catalogos",
    "/usuarios",
    "/configuracion",
    "/mi-clave",
]


def _en_base(consulta):
    with db.SessionLocal() as s:
        return s.scalars(consulta).all()


def _uno(consulta):
    filas = _en_base(consulta)
    assert len(filas) == 1, f"se esperaba una fila y hay {len(filas)}"
    return filas[0]


@pytest.fixture
def equipo(cliente, otro_cliente):
    """Cuatro navegadores creados por el administrador: administrador, creador de EMPRESA A (carla),
    creador de EMPRESA B (diana, «creador2») y revisor (andres)."""
    entrar(cliente, "admin", CLAVE_ADMIN)
    empresas = {}
    for nombre in ("EMPRESA A", "EMPRESA B"):
        assert publicar(cliente, "/empresas/nueva", {"nombre": nombre}).status_code == 303
        empresas[nombre] = str(_uno(select(Empresa).where(Empresa.nombre == nombre)).id)
    for usuario, rol, empresa in (
        ("carla", "creador", "EMPRESA A"), ("diana", "creador", "EMPRESA B"), ("andres", "aprobador", None)
    ):
        respuesta = publicar(
            cliente,
            "/usuarios/nuevo",
            {"usuario": usuario, "nombre": usuario.capitalize(), "clave": clave_de(usuario), "rol": rol,
             "empresa_id": empresas.get(empresa, "")},
        )
        assert respuesta.status_code == 303
        _uno(select(Usuario).where(Usuario.usuario == usuario))  # se creó de verdad
    creador, creador2, aprobador = otro_cliente(), otro_cliente(), otro_cliente()
    entrar(creador, "carla", clave_de("carla"))
    entrar(creador2, "diana", clave_de("diana"))
    entrar(aprobador, "andres", clave_de("andres"))
    return {"admin": cliente, "creador": creador, "creador2": creador2, "aprobador": aprobador}


def _credito_antiguo(pid: int, tipo: str = "dias", valor=15) -> None:
    """La facturación (fuera de alcance del crédito por empresa) sigue leyendo las columnas antiguas
    `Proveedor.credito_tipo/credito_valor`, que ya no escribe ninguna pantalla: las pruebas de facturas las fijan aquí."""
    with db.SessionLocal() as s:
        p = s.get(Proveedor, pid)
        p.credito_tipo, p.credito_valor = tipo, valor
        s.commit()


def _crear_proveedor(navegador, ids_catalogo, **cambios) -> int:
    respuesta = publicar(navegador, "/proveedores/nuevo", formulario_proveedor(ids_catalogo, **cambios))
    assert respuesta.status_code == 303, respuesta.text
    return int(respuesta.headers["location"].rsplit("/", 1)[1])


# ---------------------------------------------------------------- sesión y seguridad


@pytest.mark.parametrize("ruta", RUTAS_PROTEGIDAS)
def test_nada_se_ve_sin_iniciar_sesion(cliente, ruta):
    respuesta = cliente.get(ruta, follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/login"


def test_paginas_publicas(cliente):
    assert cliente.get("/salud").json() == {"estado": "ok"}
    login = cliente.get("/login")
    assert login.status_code == 200
    assert "Iniciar sesión" in login.text
    assert login.headers["x-frame-options"] == "DENY"
    assert login.headers["cache-control"] == "no-store"
    assert cliente.get("/static/htmx.min.js").status_code == 200
    assert cliente.get("/static/estilo.css").status_code == 200


def test_el_administrador_inicial_viene_del_entorno_con_clave_cifrada(cliente):
    admin = _uno(select(Usuario))
    assert admin.usuario == "admin" and admin.rol == ADMINISTRADOR
    assert admin.clave_hash.startswith("$argon2")
    assert CLAVE_ADMIN not in admin.clave_hash


def test_login_correcto_e_incorrecto(cliente):
    mala = cliente.post(
        "/login", data={"usuario": "admin", "clave": "no-es-la-clave", "csrf_token": ayudas.token(cliente, "/login")}
    )
    assert mala.status_code == 401
    assert "incorrectos" in mala.text
    assert cliente.get("/", follow_redirects=False).status_code == 303

    entrar(cliente, "admin", CLAVE_ADMIN)
    panel = cliente.get("/")
    assert panel.status_code == 200
    assert "Panel de pagos" in panel.text

    assert publicar(cliente, "/salir").status_code == 303
    assert cliente.get("/", follow_redirects=False).status_code == 303


def test_la_cookie_de_sesion_no_es_legible_por_scripts(cliente):
    respuesta = cliente.post(
        "/login",
        data={"usuario": "admin", "clave": CLAVE_ADMIN, "csrf_token": ayudas.token(cliente, "/login")},
        follow_redirects=False,
    )
    cookie = respuesta.headers["set-cookie"].lower()
    assert "proveedores_sesion=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_bloqueo_tras_varios_intentos_fallidos(cliente):
    for _ in range(5):
        respuesta = cliente.post(
            "/login", data={"usuario": "admin", "clave": "mala", "csrf_token": ayudas.token(cliente, "/login")}
        )
        assert respuesta.status_code == 401
    bloqueada = cliente.post(
        "/login", data={"usuario": "admin", "clave": CLAVE_ADMIN, "csrf_token": ayudas.token(cliente, "/login")}
    )
    assert bloqueada.status_code == 429


def test_post_sin_token_csrf_se_rechaza(cliente):
    entrar(cliente, "admin", CLAVE_ADMIN)
    datos = {"usuario": "intruso", "nombre": "Intruso", "clave": "clave-intruso-123", "rol": "administrador"}

    assert cliente.post("/usuarios/nuevo", data=datos, follow_redirects=False).status_code == 403
    con_token_falso = dict(datos, csrf_token="token-falso")
    assert cliente.post("/usuarios/nuevo", data=con_token_falso, follow_redirects=False).status_code == 403
    assert len(_en_base(select(Usuario))) == 1

    # el mismo envío con el token correcto sí funciona (por campo o por cabecera, como hace HTMX)
    assert publicar(cliente, "/usuarios/nuevo", datos).status_code == 303
    cabecera = {"X-CSRF-Token": ayudas.token(cliente)}
    otro = dict(datos, usuario="intruso2")
    assert cliente.post("/usuarios/nuevo", data=otro, headers=cabecera, follow_redirects=False).status_code == 303
    assert len(_en_base(select(Usuario))) == 3


def test_cambiar_mi_clave(cliente):
    entrar(cliente, "admin", CLAVE_ADMIN)
    mal = publicar(cliente, "/mi-clave", {"actual": "no-es", "nueva": "nueva-clave-456", "repetida": "nueva-clave-456"})
    assert mal.status_code == 400
    corta = publicar(cliente, "/mi-clave", {"actual": CLAVE_ADMIN, "nueva": "corta", "repetida": "corta"})
    assert corta.status_code == 400
    bien = publicar(cliente, "/mi-clave", {"actual": CLAVE_ADMIN, "nueva": "nueva-clave-456", "repetida": "nueva-clave-456"})
    assert bien.status_code == 303
    assert cliente.get("/").status_code == 200  # sigue con sesión

    publicar(cliente, "/salir")
    entrar(cliente, "admin", "nueva-clave-456")


# ---------------------------------------------------------------- permisos por perfil


def test_permisos_del_creador(equipo, ids_catalogo):
    creador = equipo["creador"]
    for ruta in ("/", "/proveedores", "/proveedores/nuevo", "/facturas", "/facturas/nueva", "/validaciones", "/historial"):
        assert creador.get(ruta).status_code == 200, ruta
    for ruta in ("/aprobaciones", "/catalogos", "/usuarios", "/configuracion"):
        assert creador.get(ruta).status_code == 403, ruta
    assert publicar(creador, "/usuarios/nuevo", {"usuario": "x", "nombre": "X", "clave": "12345678", "rol": "creador"}).status_code == 403
    assert publicar(creador, "/configuracion", {"dias_aviso": "3", "contrapartida": "9"}).status_code == 403
    assert publicar(creador, "/catalogos/bancos/nuevo", {"codigo": "1", "nombre": "X"}).status_code == 403


def test_permisos_del_aprobador(equipo, ids_catalogo):
    aprobador = equipo["aprobador"]
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    for ruta in ("/", "/proveedores", f"/proveedores/{pid}", "/facturas", "/aprobaciones", "/validaciones", "/historial"):
        assert aprobador.get(ruta).status_code == 200, ruta
    for ruta in ("/proveedores/nuevo", f"/proveedores/{pid}/editar", "/facturas/nueva", "/catalogos", "/usuarios", "/configuracion"):
        assert aprobador.get(ruta).status_code == 403, ruta
    assert publicar(aprobador, "/proveedores/nuevo", formulario_proveedor(ids_catalogo, numero_id="0190000000002")).status_code == 403
    assert publicar(aprobador, f"/proveedores/{pid}/editar", formulario_proveedor(ids_catalogo, numero_cuenta="0000000001")).status_code == 403
    assert publicar(aprobador, f"/proveedores/{pid}/activo", {"activo": "0"}).status_code == 403
    assert publicar(aprobador, "/facturas/nueva", {"proveedor_id": str(pid), "numero": "F-1", "fecha": "2026-03-10", "valor": "10"}).status_code == 403
    assert publicar(aprobador, "/facturas/exportar", {"ids": ["1"]}).status_code == 403

    p = _uno(select(Proveedor))
    assert p.numero_cuenta == "0009876543" and p.activo is True
    assert _en_base(select(Factura)) == []


def test_el_creador_no_puede_aprobar_ni_por_url_directa(equipo, ids_catalogo):
    pid = _crear_proveedor(equipo["creador"], ids_catalogo)
    assert publicar(equipo["creador"], f"/aprobaciones/{pid}/aprobar").status_code == 403
    assert publicar(equipo["creador"], "/aprobaciones/lote", {"ids": [str(pid)]}).status_code == 403
    assert publicar(equipo["creador"], f"/aprobaciones/{pid}/rechazar", {"motivo": "x"}).status_code == 403
    assert _uno(select(Proveedor)).estado_aprobacion == PENDIENTE


def test_el_administrador_no_aprueba_lo_que_el_mismo_creo(equipo, ids_catalogo):
    admin = equipo["admin"]
    pid = _crear_proveedor(admin, ids_catalogo)
    assert "usted mismo cre" in admin.get("/aprobaciones").text  # se le explica por qué no puede

    assert publicar(admin, f"/aprobaciones/{pid}/aprobar").status_code == 303
    assert publicar(admin, "/aprobaciones/lote", {"ids": [str(pid)]}).status_code == 303
    assert _uno(select(Proveedor)).estado_aprobacion == PENDIENTE

    assert publicar(equipo["aprobador"], f"/aprobaciones/{pid}/aprobar").status_code == 303
    assert _uno(select(Proveedor)).estado_aprobacion == APROBADO


def test_rechazo_con_motivo_y_reenvio(equipo, ids_catalogo):
    creador, aprobador = equipo["creador"], equipo["aprobador"]
    pid = _crear_proveedor(creador, ids_catalogo)

    assert publicar(aprobador, f"/aprobaciones/{pid}/rechazar", {"motivo": ""}).status_code == 303
    assert _uno(select(Proveedor)).estado_aprobacion == PENDIENTE  # sin motivo no se rechaza

    assert publicar(aprobador, f"/aprobaciones/{pid}/rechazar", {"motivo": "La cuenta no coincide"}).status_code == 303
    p = _uno(select(Proveedor))
    assert p.estado_aprobacion == "rechazado" and p.motivo_rechazo == "La cuenta no coincide"
    assert "La cuenta no coincide" in creador.get(f"/proveedores/{pid}").text

    corregido = formulario_proveedor(ids_catalogo, numero_cuenta="0009876500")
    assert publicar(creador, f"/proveedores/{pid}/editar", corregido).status_code == 303
    assert _uno(select(Proveedor)).estado_aprobacion == PENDIENTE


def test_aprobacion_en_bloque(equipo, ids_catalogo):
    creador, aprobador = equipo["creador"], equipo["aprobador"]
    ids = [
        _crear_proveedor(creador, ids_catalogo, nombre=f"PROVEEDOR EN BLOQUE {i}", numero_id=f"019000000{i:04d}")
        for i in range(1, 4)
    ]
    pagina = aprobador.get("/aprobaciones")
    assert pagina.status_code == 200
    assert "PROVEEDOR EN BLOQUE 1" in pagina.text and "Marcar seleccionados como revisados" in pagina.text

    assert publicar(aprobador, "/aprobaciones/lote", {"ids": [str(i) for i in ids[:2]]}).status_code == 303
    estados = {p.id: p.estado_aprobacion for p in _en_base(select(Proveedor))}
    assert estados == {ids[0]: APROBADO, ids[1]: APROBADO, ids[2]: PENDIENTE}


def test_usuarios_desactivar_y_ultimo_administrador(equipo):
    admin = equipo["admin"]
    carla = _uno(select(Usuario).where(Usuario.usuario == "carla"))
    assert equipo["creador"].get("/").status_code == 200

    # sin la casilla "activo" el usuario queda desactivado y pierde la sesión
    assert publicar(admin, f"/usuarios/{carla.id}", {"nombre": "Carla", "rol": "creador"}).status_code == 303
    assert equipo["creador"].get("/", follow_redirects=False).status_code == 303

    yo = _uno(select(Usuario).where(Usuario.usuario == "admin"))
    publicar(admin, f"/usuarios/{yo.id}", {"nombre": "Admin", "rol": "creador", "activo": "1"})
    publicar(admin, f"/usuarios/{yo.id}", {"nombre": "Admin", "rol": "administrador"})
    yo = _uno(select(Usuario).where(Usuario.usuario == "admin"))
    assert yo.rol == ADMINISTRADOR and yo.activo is True, "debe quedar siempre un administrador activo"


# ---------------------------------------------------------------- catálogos por la web


def _excel_minimo() -> bytes:
    libro = openpyxl.Workbook()
    libro.active.title = "MAESTRO"
    libro.active.append(["PROVEEDOR QUE NO DEBE LEERSE", "30"])
    hoja = libro.create_sheet("Hoja2")
    hoja.append(["TIPO ID", None, None, "Código de instituciones financieras"])
    hoja.append(["C", "CEDULA", None, "Código Banco", "Nombre del Banco"])
    hoja.append(["R", "RUC", None, 9911, "BANCO INVENTADO PARA LA WEB"])
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def test_cargar_catalogos_desde_la_pantalla(equipo):
    admin = equipo["admin"]
    pagina = admin.get("/catalogos")
    assert pagina.status_code == 200
    assert "oficiales" in pagina.text
    assert "BANCO PICHINCHA C.A." in pagina.text  # la semilla viene con la app

    archivos = {"archivo": ("catalogos.xlsx", _excel_minimo(), XLSX)}
    respuesta = admin.post("/catalogos/cargar-excel", data={"csrf_token": ayudas.token(admin)}, files=archivos)
    assert respuesta.status_code == 200
    assert "Instituciones financieras agregadas: 1" in respuesta.text
    assert _uno(select(Banco).where(Banco.nombre == "BANCO INVENTADO PARA LA WEB")).codigo == "9911"
    assert _en_base(select(Proveedor)) == []

    repetida = admin.post("/catalogos/cargar-excel", data={"csrf_token": ayudas.token(admin)}, files=archivos)
    assert "Instituciones financieras agregadas: 0" in repetida.text

    creador = equipo["creador"]
    intento = creador.post("/catalogos/cargar-excel", data={"csrf_token": ayudas.token(creador)}, files=archivos)
    assert intento.status_code == 403


def test_editar_catalogos_a_mano(equipo):
    admin = equipo["admin"]
    assert publicar(admin, "/catalogos/bancos/nuevo", {"codigo": "0099", "nombre": "BANCO AGREGADO A MANO"}).status_code == 303
    banco = _uno(select(Banco).where(Banco.nombre == "BANCO AGREGADO A MANO"))
    assert banco.codigo == "0099"

    assert publicar(admin, f"/catalogos/bancos/{banco.id}", {"codigo": "0100", "nombre": "BANCO AGREGADO A MANO"}).status_code == 303
    banco = _uno(select(Banco).where(Banco.nombre == "BANCO AGREGADO A MANO"))
    assert banco.codigo == "0100" and banco.activo is False  # sin la casilla queda inactivo

    parcial = admin.get("/catalogos?q=AGREGADO", headers={"HX-Request": "true"})
    assert "BANCO AGREGADO A MANO" in parcial.text and "<html" not in parcial.text

    assert publicar(admin, "/catalogos/tipos-id/nuevo", {"codigo": "x", "nombre": "carnet inventado"}).status_code == 303
    assert "CARNET INVENTADO" in admin.get("/catalogos").text


# ---------------------------------------------------------------- recorrido completo


def test_recorrido_completo_de_creador_y_aprobador(equipo, ids_catalogo):
    admin, creador, aprobador = equipo["admin"], equipo["creador"], equipo["aprobador"]
    hoy = config.hoy()

    # 1. El creador registra el proveedor a mano; nace pendiente y conserva los ceros a la izquierda.
    pid = _crear_proveedor(creador, ids_catalogo)
    _credito_antiguo(pid)  # 15 días, para el vencimiento de sus facturas
    ficha = creador.get(f"/proveedores/{pid}")
    assert ficha.status_code == 200
    assert "DISTRIBUIDORA FICTICIA CIA. LTDA." in ficha.text
    assert "0190000000001" in ficha.text and "0009876543" in ficha.text
    assert "insignia-pendiente" in ficha.text
    p = _uno(select(Proveedor))
    assert (p.numero_id, p.numero_cuenta, p.estado_aprobacion) == ("0190000000001", "0009876543", PENDIENTE)

    # 2. Búsqueda por nombre, identificación y banco (también la parcial de HTMX).
    for texto in ("ficticia", "0190000000001", "inventado de prueba"):
        assert "DISTRIBUIDORA FICTICIA" in creador.get("/proveedores", params={"q": texto}).text, texto
    assert "No hay proveedores que coincidan" in creador.get("/proveedores", params={"q": "zzzz"}).text
    parcial = creador.get("/proveedores", params={"q": "ficticia"}, headers={"HX-Request": "true"})
    assert "DISTRIBUIDORA FICTICIA" in parcial.text and "<html" not in parcial.text
    assert "DISTRIBUIDORA FICTICIA" in creador.get("/proveedores", params={"aprobacion": "pendiente"}).text
    assert "DISTRIBUIDORA FICTICIA" not in creador.get("/proveedores", params={"aprobacion": "aprobado"}).text

    # 3. El aprobador lo ve en su bandeja, con el contador en el menú.
    bandeja = aprobador.get("/aprobaciones")
    assert "DISTRIBUIDORA FICTICIA CIA. LTDA." in bandeja.text
    assert "Proveedor nuevo" in bandeja.text
    assert '<span class="contador">1</span>' in aprobador.get("/").text

    # 4. El creador registra dos facturas: una que vence hoy (fechada hace 15 días) y una de hoy (vence en 15 días).
    for numero, fecha, valor in (
        ("001-002-000000045", hoy - timedelta(days=15), "480.75"),
        ("001-002-000000046", hoy, "1000"),
    ):
        respuesta = publicar(
            creador,
            "/facturas/nueva",
            {"proveedor_id": str(pid), "numero": numero, "fecha": fecha.isoformat(), "valor": valor, "moneda": "USD", "notas": ""},
        )
        assert respuesta.status_code == 303, respuesta.text
    de_hoy = _uno(select(Factura).where(Factura.numero == "001-002-000000045"))
    futura = _uno(select(Factura).where(Factura.numero == "001-002-000000046"))
    assert de_hoy.vencimiento == hoy
    assert futura.vencimiento == hoy + timedelta(days=15)

    # 5. El panel muestra cada una el día que corresponde.
    panel = creador.get("/").text
    assert "001-002-000000045" in panel  # vence hoy
    assert "001-002-000000046" not in panel  # vence en 15 días y el aviso por defecto es de 7
    assert "001-002-000000046" not in creador.get("/", params={"dias": "14"}).text
    assert "001-002-000000046" in creador.get("/", params={"dias": "15"}).text

    # 6. Mientras el proveedor no esté aprobado, sus facturas no salen en el archivo de pago.
    bloqueado = publicar(creador, "/facturas/exportar", {"ids": [str(de_hoy.id)]})
    assert bloqueado.status_code == 400
    assert "no está revisado" in bloqueado.text
    assert "No exportable" in creador.get("/facturas").text

    # 7. El aprobador aprueba.
    assert publicar(aprobador, f"/aprobaciones/{pid}/aprobar").status_code == 303
    assert "insignia-aprobado" in creador.get(f"/proveedores/{pid}").text
    aprobador.get("/")  # consume el mensaje "Revisado: ..." que se muestra una sola vez
    assert "No hay proveedores pendientes de revisión" in aprobador.get("/aprobaciones").text

    # 8. Ahora sí se genera el archivo de pago masivo, con el formato de la hoja de pago.
    archivo = publicar(creador, "/facturas/exportar", {"ids": [str(de_hoy.id), str(futura.id)]})
    assert archivo.status_code == 200
    assert archivo.headers["content-type"].startswith(XLSX)
    assert "attachment" in archivo.headers["content-disposition"]
    hoja = openpyxl.load_workbook(io.BytesIO(archivo.content))["Hoja 1"]
    filas = list(hoja.iter_rows(values_only=True))
    assert len(filas) == 3
    primera = dict(zip(filas[0], filas[1]))
    assert primera["NOMBRE"] == primera["NOMBRE BENEFICIARIO"] == "DISTRIBUIDORA FICTICIA CIA. LTDA."
    assert primera["TIPO"] == "PA" and primera["FORMA DE PAGO"] == "CTA" and primera["MONEDA"] == "USD"
    assert primera["VALOR"] == pytest.approx(480.75)
    assert primera["TIPO CTA"] == "AHO" and primera["NUMERO CTA"] == "0009876543"
    assert primera["TIPO ID"] == "RUC" and primera["NUMERO ID"] == "0190000000001"
    assert primera["CODIGOS BANCOS"] == "0042"
    assert primera["REFERENCIA"] == "PAGO FAC 001-002-000000045 DISTRIBUIDORA FICTICIA CIA. LTDA."
    assert primera["DIAS CREDITO"] == "15"
    assert _uno(select(Factura).where(Factura.id == de_hoy.id)).exportada_en is not None

    # 9. Cambiar la cuenta deja historial y devuelve al proveedor a pendiente: vuelve a bloquearse el pago.
    cambio = formulario_proveedor(ids_catalogo, numero_cuenta="0001112223")
    assert publicar(creador, f"/proveedores/{pid}/editar", cambio).status_code == 303
    assert _uno(select(Proveedor)).estado_aprobacion == PENDIENTE
    historial = admin.get("/historial", params={"solo": "bancarios"}).text
    assert "0009876543" in historial and "0001112223" in historial and "carla" in historial
    revision = aprobador.get("/aprobaciones").text
    assert "0009876543" in revision and "0001112223" in revision
    assert publicar(creador, "/facturas/exportar", {"ids": [str(futura.id)]}).status_code == 400
    assert publicar(aprobador, f"/aprobaciones/{pid}/aprobar").status_code == 303

    # 10. Se marca como pagada (también por HTMX) y sale del panel.
    assert publicar(aprobador, f"/facturas/{de_hoy.id}/pagar").status_code == 403
    por_htmx = creador.post(
        f"/facturas/{de_hoy.id}/pagar", headers={"HX-Request": "true", "X-CSRF-Token": ayudas.token(creador)}
    )
    assert por_htmx.status_code == 200 and por_htmx.headers["hx-refresh"] == "true"
    assert _uno(select(Factura).where(Factura.id == de_hoy.id)).estado == FACTURA_PAGADA
    assert "marcada como pagada" in creador.get("/facturas").text  # mensaje de una sola vez
    assert "001-002-000000045" not in creador.get("/").text

    # 11. Exportar el listado de proveedores.
    listado = aprobador.get("/proveedores/exportar")
    assert listado.status_code == 200 and listado.headers["content-type"].startswith(XLSX)
    filas = list(openpyxl.load_workbook(io.BytesIO(listado.content))["Proveedores"].iter_rows(values_only=True))
    assert dict(zip(filas[0], filas[1]))["NUMERO CTA"] == "0001112223"

    # 12. Desactivar en lugar de borrar.
    assert publicar(creador, f"/proveedores/{pid}/activo", {"activo": "0"}).status_code == 303
    assert _uno(select(Proveedor)).activo is False
    assert "DISTRIBUIDORA FICTICIA" not in creador.get("/proveedores").text
    assert "DISTRIBUIDORA FICTICIA" in creador.get("/proveedores", params={"estado": "inactivos"}).text


def test_formulario_de_proveedor_muestra_errores(equipo, ids_catalogo):
    creador = equipo["creador"]
    respuesta = publicar(creador, "/proveedores/nuevo", formulario_proveedor(ids_catalogo, numero_id="123", correo="malo"))
    assert respuesta.status_code == 400
    assert "13 dígitos" in respuesta.text and "correo" in respuesta.text
    assert _en_base(select(Proveedor)) == []

    pid = _crear_proveedor(creador, ids_catalogo)
    # Repetir la identificación ya no es un error: se reconoce el proveedor existente (ver test_proveedor_empresas).
    repetido = publicar(creador, "/proveedores/nuevo", formulario_proveedor(ids_catalogo, nombre="OTRO NOMBRE"))
    assert repetido.status_code == 303 and repetido.headers["location"] == f"/proveedores/{pid}"
    # Editar otro proveedor con una identificación ya usada sí se rechaza.
    otro = _crear_proveedor(creador, ids_catalogo, numero_id="0990000000001")
    repetido = publicar(creador, f"/proveedores/{otro}/editar", formulario_proveedor(ids_catalogo))
    assert repetido.status_code == 400 and "Ya existe" in repetido.text


def test_configuracion_y_respaldo_manual(equipo, entorno):
    admin = equipo["admin"]
    assert admin.get("/configuracion").status_code == 200
    assert publicar(admin, "/configuracion", {"dias_aviso": "10", "contrapartida": "3"}).status_code == 303
    pagina = admin.get("/configuracion").text
    assert 'value="10"' in pagina and 'value="3"' in pagina
    assert "Próximos 10 días" in admin.get("/").text

    assert publicar(admin, "/configuracion/respaldar").status_code == 303
    assert len(list(entorno.ruta_respaldos.glob("proveedores-*.db"))) == 1
    assert publicar(admin, "/configuracion/revisar-alarmas").status_code == 303
    assert "correo enviado: no" in admin.get("/configuracion").text
