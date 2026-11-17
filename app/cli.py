"""Comandos de mantenimiento.

    python -m app.cli cargar-catalogos [ruta.xlsx]   Agrega catálogos desde la hoja de catálogos del Excel
    python -m app.cli importar-proveedores RUTA --usuario U [--empresa NOMBRE] [--aplicar]
                                                     Importa proveedores desde un Excel (sin --aplicar solo simula)
    python -m app.cli respaldar                      Crea un respaldo de la base ahora
    python -m app.cli clave USUARIO                  Cambia la contraseña de un usuario (la pide por teclado)
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from . import catalogos, config, db, importacion, seguridad, servicios, tareas
from .modelos import Usuario
from .servicios import ErrorNegocio


def _abrir():
    cfg = config.cargar()
    db.iniciar_bd(cfg.ruta_bd)
    sesion = db.SessionLocal()
    catalogos.preparar_bd(sesion)
    return cfg, sesion


def cargar_catalogos(ruta: str = None) -> int:
    cfg, sesion = _abrir()
    try:
        origen = ruta or cfg.ruta_excel
        resumen = catalogos.cargar_desde_excel(sesion, origen)
    except ErrorNegocio as error:
        print(f"ERROR: {error}")
        return 1
    except FileNotFoundError:
        print(f"ERROR: no existe el archivo {origen}")
        return 1
    finally:
        sesion.close()
    print(f"Catálogos cargados desde la hoja «{catalogos.HOJA_CATALOGOS}» (no se leyó ninguna otra hoja).")
    for linea in resumen.lineas():
        print("  " + linea)
    for texto in resumen.avisos:
        print("  AVISO: " + texto)
    return 0


def importar_proveedores(ruta: str, nombre_usuario: str, aplicar: bool, nombre_empresa: str = None) -> int:
    cfg, sesion = _abrir()
    try:
        u = sesion.scalars(select(Usuario).where(Usuario.usuario == nombre_usuario.strip().lower())).first()
        if u is None or not u.activo:
            print("ERROR: el usuario indicado no existe o está desactivado.")
            return 1
        empresa = None
        if nombre_empresa is not None:
            buscada = servicios.normalizar(nombre_empresa)
            empresa = next((e for e in servicios.empresas_activas(sesion) if e.nombre_norm == buscada), None)
            if empresa is None:
                print("ERROR: la empresa indicada no existe; créela antes en Administración → Empresas.")
                return 1
        try:
            resumen = importacion.importar(sesion, ruta, u, empresa)
        except FileNotFoundError:
            print(f"ERROR: no existe el archivo {ruta}")
            return 1
        except ErrorNegocio as error:
            print(f"ERROR: {error}")
            return 1
        print("SIMULACIÓN: no se guardará nada." if not aplicar else "IMPORTACIÓN REAL.")
        for linea in resumen.lineas():
            print("  " + linea)
        if resumen.omitidos:
            print("\nOmitidos (hoja, fila, motivo); busque la fila en el Excel:")
            for hoja, fila, motivo in resumen.omitidos:
                print(f"  - {hoja}, fila {fila}: {motivo}")
        if resumen.avisos:
            print("\nImportados con algo que revisar (hoja, fila):")
            for hoja, fila, motivo in resumen.avisos:
                print(f"  - {hoja}, fila {fila}: {motivo}")
        if not aplicar:
            sesion.rollback()
            print("\nNo se guardó nada. Si el resultado es el esperado, repita el comando agregando --aplicar.")
            return 0
        if resumen.importados == 0:
            sesion.rollback()
            print("\nNo había proveedores nuevos que importar.")
            return 0
        if cfg.ruta_bd.is_file():
            print(f"\nRespaldo previo: {tareas.respaldar().name}")
        sesion.commit()
        pendientes = resumen.importados - resumen.aprobados
        print(
            f"Listo: {resumen.importados} proveedores importados: {resumen.aprobados} ya revisados (REGISTRADO = OK) "
            f"y {pendientes} pendientes de revisión por otra persona."
        )
        return 0
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()


def respaldar() -> int:
    cfg = config.cargar()
    if not cfg.ruta_bd.is_file():
        print(f"ERROR: no existe la base de datos {cfg.ruta_bd}")
        return 1
    destino = tareas.respaldar()
    print(f"Respaldo creado: {destino}")
    return 0


def cambiar_clave(nombre_usuario: str) -> int:
    _cfg, sesion = _abrir()
    try:
        u = sesion.scalars(select(Usuario).where(Usuario.usuario == nombre_usuario.strip().lower())).first()
        if u is None:
            print("ERROR: no existe ese usuario.")
            return 1
        clave = getpass.getpass("Contraseña nueva: ")
        if clave != getpass.getpass("Repítala: "):
            print("ERROR: no coinciden.")
            return 1
        error = seguridad.error_clave(clave)
        if error:
            print("ERROR: " + error)
            return 1
        u.clave_hash = seguridad.cifrar(clave)
        u.activo = True
        sesion.commit()
        print(f"Contraseña cambiada para {u.usuario}.")
        return 0
    finally:
        sesion.close()


def main(argumentos=None) -> int:
    analizador = argparse.ArgumentParser(prog="python -m app.cli", description="Mantenimiento de Manejo de Proveedores")
    comandos = analizador.add_subparsers(dest="comando", required=True)
    c = comandos.add_parser("cargar-catalogos", help="Agrega catálogos desde la hoja de catálogos del Excel")
    c.add_argument("ruta", nargs="?", help="Ruta del .xlsx (por defecto, RUTA_EXCEL)")
    i = comandos.add_parser("importar-proveedores", help="Importa proveedores desde un Excel (simula si no se usa --aplicar)")
    i.add_argument("ruta", help="Ruta del .xlsx")
    i.add_argument("--usuario", required=True, help="Usuario que figura como creador de los proveedores")
    i.add_argument("--aplicar", action="store_true", help="Guardar de verdad (sin esto solo se simula)")
    i.add_argument("--empresa", help="Empresa a la que pertenece el crédito del Excel (sin esto no se importa el crédito)")
    comandos.add_parser("respaldar", help="Crea un respaldo de la base de datos")
    k = comandos.add_parser("clave", help="Cambia la contraseña de un usuario")
    k.add_argument("usuario")
    args = analizador.parse_args(argumentos)
    if args.comando == "cargar-catalogos":
        return cargar_catalogos(args.ruta)
    if args.comando == "importar-proveedores":
        return importar_proveedores(args.ruta, args.usuario, args.aplicar, args.empresa)
    if args.comando == "respaldar":
        return respaldar()
    return cambiar_clave(args.usuario)


if __name__ == "__main__":
    sys.exit(main())
