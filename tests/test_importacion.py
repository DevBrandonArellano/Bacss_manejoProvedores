"""Importación de proveedores desde Excel. Usa libros inventados, nunca datos reales."""
import openpyxl
import pytest
from sqlalchemy import select

import ayudas
from app import cli, db, importacion
from app.modelos import APROBADO, PENDIENTE, Banco, Historial, Proveedor, ProveedorCredito
from app.servicios import ErrorNegocio

ENCABEZADOS = [None, "DÍAS CREDITO ", "REGISTRADO", "TIPO ID", "NUMERO ID", None, "TIPO CTA", "NUMERO CTA", " BANCOS", None, "CORREO", None, None]


def fila(nombre, credito, registrado, tipo, numero, tipo_cta, cuenta, banco, codigo=None, correo=None, nota=None):
    return [nombre, credito, registrado, tipo, numero, None, tipo_cta, cuenta, banco, codigo, correo, None, nota]


def libro(tmp_path, hojas: dict, extra: dict = None):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nombre, filas in hojas.items():
        ws = wb.create_sheet(nombre)
        ws.append(ENCABEZADOS)
        for f in filas:
            ws.append(f)
    for nombre, filas in (extra or {}).items():  # hojas que NO son de proveedores
        ws = wb.create_sheet(nombre)
        for f in filas:
            ws.append(f)
    ruta = tmp_path / "prov.xlsx"
    wb.save(ruta)
    return ruta


@pytest.fixture
def base(sesion, personas):
    return sesion, personas["admin"]


def _todos(sesion):
    return sesion.scalars(select(Proveedor).order_by(Proveedor.id)).all()


def _credito(p, empresa):
    """(tipo, valor) del crédito de `empresa` con `p`; (None, None) si no tiene."""
    fila = p.credito_de(empresa.id)
    return (fila.credito_tipo, fila.credito_valor) if fila is not None else (None, None)


def test_importa_con_las_mismas_reglas_del_alta_manual(base, tmp_path):
    sesion, actor = base
    ruta = libro(
        tmp_path,
        {
            "UNO": [
                fila("EMPRESA UNO S.A.", "30 DIAS", "OK", "RUC", "0990000000001", "CTE", "0001112223", "BANCO PICHINCHA C.A.", correo="a@uno.test; b@uno.test", nota="INSUMOS"),
                fila("PERSONA DOS", "CONTADO", None, "CEDULA", "0912345675", "AHO", "0004445556", "BANCO PICHINCHA C.A."),
                fila("TRES SA", "FIN DE MES", None, "RUC", "1790000000001", "CTE", "77", "BANCO PICHINCHA C.A."),
                fila("CUATRO SA", "29 DE CADA MES", None, "RUC", "1790000000002", "CTE", "88", "BANCO PICHINCHA C.A."),
            ],
        },
        extra={"Hoja 1": [["NOMBRE", "TIPO ID", "NUMERO ID", "CODIGOS BANCOS"], ["OTRO", "RUC", "0990000000099", 10]]},
    )
    empresa = ayudas.empresa(sesion, "EMPRESA A")
    resumen = importacion.importar(sesion, ruta, actor, empresa)
    sesion.commit()
    assert resumen.hojas == ["UNO"]  # «Hoja 1» (pago masivo) no es una hoja de proveedores
    assert resumen.importados == 4 and not resumen.omitidos
    uno, dos, tres, cuatro = _todos(sesion)
    assert uno.creado_por_id == actor.id
    # Marcado OK en el Excel: ya estaba aprobado. Los demás quedan pendientes.
    assert uno.estado_aprobacion == APROBADO and uno.aprobado_en is not None and uno.aprobado_por_id is None
    assert all(p.estado_aprobacion == PENDIENTE for p in (dos, tres, cuatro))
    assert (resumen.importados, resumen.aprobados) == (4, 1)
    assert (uno.numero_id, uno.numero_cuenta) == ("0990000000001", "0001112223")  # conserva los ceros
    assert uno.tipo_id.codigo == "R" and uno.tipo_cuenta.codigo == "CTE"
    assert uno.banco.nombre == "BANCO PICHINCHA C.A."
    assert _credito(uno, empresa) == ("dias", 30) and uno.registrado_banco is True
    assert uno.credito_tipo is None  # la columna antigua ya no se escribe
    assert resumen.creditos == 4 and "Créditos importados: 4" in resumen.lineas()
    assert uno.correo == "a@uno.test; b@uno.test" and "INSUMOS" in uno.notas
    assert (*_credito(dos, empresa), dos.registrado_banco) == ("dias", 0, False)
    assert dos.tipo_id.codigo == "C" and dos.tipo_cuenta.codigo == "AHO"
    assert _credito(tres, empresa) == ("fin_mes", None) and _credito(cuatro, empresa) == ("dia_fijo", 29)
    historial = sesion.scalars(select(Historial).where(Historial.proveedor_id == uno.id)).all()
    assert [(h.tipo, h.campo) for h in historial] == [
        ("creacion", "Proveedor"), ("cambio", "Crédito · EMPRESA A"), ("aprobacion", "Estado de revisión")]
    assert "REGISTRADO = OK" in historial[2].valor_nuevo
    assert [h.tipo for h in sesion.scalars(select(Historial).where(Historial.proveedor_id == dos.id)).all()] == [
        "creacion", "cambio"]


def test_se_puede_repetir_sin_duplicar(base, tmp_path):
    sesion, actor = base
    ruta = libro(tmp_path, {"UNO": [fila("A SA", "30", None, "RUC", "0990000000001", "CTE", "1", "BANCO PICHINCHA C.A.")]})
    assert importacion.importar(sesion, ruta, actor).importados == 1
    sesion.commit()
    otra = importacion.importar(sesion, ruta, actor)
    assert (otra.importados, otra.ya_existian) == (0, 1)
    assert len(_todos(sesion)) == 1


def test_no_pisa_cambios_hechos_a_mano(base, tmp_path):
    sesion, actor = base
    ruta = libro(tmp_path, {"UNO": [fila("A SA", "30", None, "RUC", "0990000000001", "CTE", "1", "BANCO PICHINCHA C.A.")]})
    importacion.importar(sesion, ruta, actor)
    sesion.commit()
    p = _todos(sesion)[0]
    p.nombre = "NOMBRE CORREGIDO"
    sesion.commit()
    importacion.importar(sesion, ruta, actor)
    sesion.commit()
    assert _todos(sesion)[0].nombre == "NOMBRE CORREGIDO"


def test_repetidos_entre_hojas_y_conflictos(base, tmp_path):
    sesion, actor = base
    igual = fila("A SA", "30", None, "RUC", "0990000000001", "CTE", "111", "BANCO PICHINCHA C.A.")
    otra_cuenta = fila("A SA", "30", None, "RUC", "0990000000001", "CTE", "999", "BANCO PICHINCHA C.A.")
    ruta = libro(tmp_path, {"UNO": [igual, otra_cuenta], "DOS": [igual]})
    resumen = importacion.importar(sesion, ruta, actor)
    sesion.commit()
    assert (resumen.importados, resumen.repetidos) == (1, 1)
    assert len(resumen.omitidos) == 1
    hoja, numero_fila, motivo = resumen.omitidos[0]
    assert (hoja, numero_fila) == ("UNO", 3) and "hoja UNO, fila 2" in motivo and "revisar a mano" in motivo
    assert _todos(sesion)[0].numero_cuenta == "111"  # gana la primera fila; la otra cuenta queda para decidir


def test_omite_lo_invalido_y_lo_explica_sin_datos_personales(base, tmp_path):
    sesion, actor = base
    ruta = libro(
        tmp_path,
        {
            "UNO": [
                fila("OK SA", "30", None, "RUC", "0990000000001", "CTE", "1", "BANCO PICHINCHA C.A."),
                fila("RUC CORTO", "30", None, "RUC", "99000", "CTE", "2", "BANCO PICHINCHA C.A."),
                fila("SIN ID", "30", None, "RUC", None, "CTE", "3", "BANCO PICHINCHA C.A."),
                fila("SIN TIPO", "30", None, None, "0990000000003", "CTE", "4", "BANCO PICHINCHA C.A."),
                fila(None, "30", None, "RUC", "0990000000004", "CTE", "5", "BANCO PICHINCHA C.A."),
                [None] * 13,  # fila vacía: se ignora sin ruido
            ],
        },
    )
    resumen = importacion.importar(sesion, ruta, actor)
    assert resumen.importados == 1 and resumen.filas_con_datos == 5
    assert [(h, n) for h, n, _ in resumen.omitidos] == [("UNO", 3), ("UNO", 4), ("UNO", 5), ("UNO", 6)]
    assert "13 dígitos" in resumen.omitidos[0][2]
    informe = " ".join(m for _, _, m in resumen.omitidos + resumen.avisos) + " ".join(resumen.lineas())
    for dato in ("RUC CORTO", "SIN ID", "99000", "0990000000003", "0990000000004"):
        assert dato not in informe


def test_banco_por_nombre_por_codigo_o_sin_banco(base, tmp_path):
    sesion, actor = base
    unico = next(b for b in sesion.scalars(select(Banco)).all() if len([x for x in sesion.scalars(select(Banco)).all() if x.codigo == b.codigo]) == 1)
    ruta = libro(
        tmp_path,
        {
            "UNO": [
                fila("A SA", None, None, "RUC", "0990000000001", "CTE", "1", "banco  pichincha c.a."),  # mayúsculas y espacios
                fila("B SA", None, None, "RUC", "0990000000002", "CTE", "2", "NOMBRE ANTIGUO DEL BANCO", codigo=int(unico.codigo) if unico.codigo.isdigit() else unico.codigo),
                fila("C SA", None, None, "RUC", "0990000000003", "CTE", "3", "BANCO QUE NO EXISTE", codigo="#N/A"),
            ],
        },
    )
    resumen = importacion.importar(sesion, ruta, actor)
    sesion.commit()
    a, b, c = _todos(sesion)
    assert a.banco.nombre == "BANCO PICHINCHA C.A."
    assert b.banco_id == unico.id
    assert c.banco_id is None
    assert [(h, n) for h, n, _ in resumen.avisos] == [("UNO", 4)] and "Banco no reconocido" in resumen.avisos[0][2]


def test_correo_invalido_y_credito_desconocido_se_avisan(base, tmp_path):
    sesion, actor = base
    ruta = libro(
        tmp_path,
        {
            "UNO": [
                fila("A SA", "CREDITO", None, "RUC", "0990000000001", "CTE", "1", "BANCO PICHINCHA C.A.", correo="esto no es correo"),
                fila("B SA", "45 D", None, "RUC", "0990000000002", "CTE", "2", "BANCO PICHINCHA C.A.", correo="x@b.test y@b.test"),
            ],
        },
    )
    empresa = ayudas.empresa(sesion, "EMPRESA A")
    resumen = importacion.importar(sesion, ruta, actor, empresa)
    sesion.commit()
    a, b = _todos(sesion)
    assert a.correo is None and "Correo original (no válido): esto no es correo" in a.notas
    assert _credito(a, empresa) == (None, None)
    assert _credito(b, empresa) == ("dias", 45) and b.correo == "x@b.test; y@b.test"
    assert {m.split(":")[0] for _, n, m in resumen.avisos if n == 2} == {"Condición de crédito no reconocida", "Correo con formato no válido"} or len(resumen.avisos) == 2


def test_sin_hojas_de_proveedores_o_sin_archivo(base, tmp_path):
    sesion, actor = base
    ruta = libro(tmp_path, {}, extra={"Otra": [["X", "Y"], [1, 2]]})
    with pytest.raises(ErrorNegocio, match="ninguna hoja de proveedores"):
        importacion.importar(sesion, ruta, actor)
    with pytest.raises(FileNotFoundError):
        importacion.importar(sesion, tmp_path / "no-existe.xlsx", actor)
    (tmp_path / "roto.xlsx").write_text("esto no es un Excel")
    with pytest.raises(ErrorNegocio, match="No se pudo abrir"):
        importacion.importar(sesion, tmp_path / "roto.xlsx", actor)


def test_comando_simula_por_defecto_y_con_aplicar_guarda_con_respaldo(entorno, tmp_path, capsys):
    ruta = libro(tmp_path, {"UNO": [fila("A SA", "30", "OK", "RUC", "0990000000001", "CTE", "1", "BANCO PICHINCHA C.A.")]})
    try:
        assert cli.main(["importar-proveedores", str(ruta), "--usuario", "admin"]) == 0
        salida = capsys.readouterr().out
        assert "SIMULACIÓN" in salida and "ya revisados (REGISTRADO = OK en el Excel): 1" in salida and "--aplicar" in salida
        with db.SessionLocal() as s:
            assert s.scalars(select(Proveedor)).all() == []  # la simulación no guarda nada

        assert cli.main(["importar-proveedores", str(ruta), "--usuario", "admin", "--aplicar"]) == 0
        salida = capsys.readouterr().out
        assert "Respaldo previo: proveedores-" in salida and "1 ya revisados" in salida and "0 pendientes" in salida
        assert any(entorno.ruta_respaldos.glob("proveedores-*.db"))
        with db.SessionLocal() as s:
            assert len(s.scalars(select(Proveedor)).all()) == 1

        assert cli.main(["importar-proveedores", str(ruta), "--usuario", "admin", "--aplicar"]) == 0
        assert "No había proveedores nuevos" in capsys.readouterr().out
        assert cli.main(["importar-proveedores", str(ruta), "--usuario", "nadie"]) == 1
        assert cli.main(["importar-proveedores", str(tmp_path / "no.xlsx"), "--usuario", "admin"]) == 1
    finally:
        db.cerrar_bd()


def test_si_solo_una_de_las_hojas_trae_ok_queda_aprobado(base, tmp_path):
    sesion, actor = base
    sin_ok = fila("A SA", "30", None, "RUC", "0990000000001", "CTE", "111", "BANCO PICHINCHA C.A.")
    con_ok = fila("A SA", "30", "OK", "RUC", "0990000000001", "CTE", "111", "BANCO PICHINCHA C.A.")
    ruta = libro(tmp_path, {"UNO": [sin_ok], "DOS": [con_ok]})
    resumen = importacion.importar(sesion, ruta, actor)
    sesion.commit()
    assert (resumen.importados, resumen.repetidos, resumen.aprobados) == (1, 1, 1)
    assert _todos(sesion)[0].estado_aprobacion == APROBADO


def test_lo_aprobado_por_el_excel_entra_en_el_pago_y_no_pide_aprobacion(base, tmp_path):
    from app.servicios import contar_pendientes

    sesion, actor = base
    ruta = libro(
        tmp_path,
        {"UNO": [
            fila("OK SA", "30", "OK", "RUC", "0990000000001", "CTE", "1", "BANCO PICHINCHA C.A."),
            fila("NO SA", "30", None, "RUC", "0990000000002", "CTE", "2", "BANCO PICHINCHA C.A."),
        ]},
    )
    importacion.importar(sesion, ruta, actor)
    sesion.commit()
    assert contar_pendientes(sesion) == 1  # solo queda por aprobar el que no venía como OK


def test_sin_empresa_no_importa_creditos(base, tmp_path):
    sesion, actor = base
    ruta = libro(tmp_path, {"UNO": [fila("A SA", "30", None, "RUC", "0990000000001", "CTE", "1", "BANCO PICHINCHA C.A.")]})
    resumen = importacion.importar(sesion, ruta, actor)
    sesion.commit()
    (p,) = _todos(sesion)
    assert p.credito_tipo is None and sesion.scalars(select(ProveedorCredito)).all() == []
    assert resumen.creditos == 0 and any("no importados" in linea for linea in resumen.lineas())


def test_la_empresa_inexistente_en_el_cli_da_error(entorno, tmp_path, capsys):
    ruta = libro(tmp_path, {"UNO": [fila("A SA", "30", None, "RUC", "0990000000001", "CTE", "1", "BANCO PICHINCHA C.A.")]})
    try:
        assert cli.main(["importar-proveedores", str(ruta), "--usuario", "admin", "--empresa", "NOEXISTE"]) == 1
        assert "no existe" in capsys.readouterr().out
    finally:
        db.cerrar_bd()


def test_el_cli_importa_el_credito_de_la_empresa_indicada(entorno, tmp_path, capsys):
    ruta = libro(tmp_path, {"UNO": [fila("A SA", "30", None, "RUC", "0990000000001", "CTE", "1", "BANCO PICHINCHA C.A.")]})
    try:
        db.iniciar_bd(entorno.ruta_bd)
        with db.SessionLocal() as s:
            from app import catalogos
            catalogos.preparar_bd(s)
            ayudas.empresa(s, "Cia Norte")
        args = ["importar-proveedores", str(ruta), "--usuario", "admin", "--empresa", "CIA NORTE", "--aplicar"]
        assert cli.main(args) == 0
        assert "Créditos importados: 1" in capsys.readouterr().out
        with db.SessionLocal() as s:
            (fila_credito,) = s.scalars(select(ProveedorCredito)).all()
            assert (fila_credito.empresa.nombre, fila_credito.credito_tipo, fila_credito.credito_valor) == ("Cia Norte", "dias", 30)
    finally:
        db.cerrar_bd()
