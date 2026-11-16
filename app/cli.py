"""Comandos de mantenimiento.

    python -m app.cli cargar-catalogos [ruta.xlsx]   Agrega catálogos desde la hoja de catálogos del Excel
    python -m app.cli respaldar                      Crea un respaldo de la base ahora
    python -m app.cli clave USUARIO                  Cambia la contraseña de un usuario (la pide por teclado)
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from . import catalogos, config, db, seguridad, tareas
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
    comandos.add_parser("respaldar", help="Crea un respaldo de la base de datos")
    k = comandos.add_parser("clave", help="Cambia la contraseña de un usuario")
    k.add_argument("usuario")
    args = analizador.parse_args(argumentos)
    if args.comando == "cargar-catalogos":
        return cargar_catalogos(args.ruta)
    if args.comando == "respaldar":
        return respaldar()
    return cambiar_clave(args.usuario)


if __name__ == "__main__":
    sys.exit(main())
