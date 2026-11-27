"""Una base creada con la versión anterior se actualiza sin perder datos."""
import sqlite3

from sqlalchemy import select

from app import db
from app.modelos import Usuario


def test_base_antigua_recibe_las_columnas_nuevas(tmp_path):
    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.executescript(
        "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, usuario VARCHAR(60), nombre VARCHAR(120), "
        "clave_hash VARCHAR(255), rol VARCHAR(20), activo BOOLEAN, creado_en DATETIME);"
        "INSERT INTO usuarios VALUES (1,'ana','Ana','x','creador',1,'2026-11-01 10:00:00');"
        "CREATE TABLE historial (id INTEGER PRIMARY KEY);"
    )
    con.commit()
    con.close()
    db.iniciar_bd(ruta)
    try:
        with db.SessionLocal() as s:
            u = s.scalars(select(Usuario)).one()
            assert u.usuario == "ana" and u.empresa_id is None
        db.iniciar_bd(ruta)  # repetirlo no falla
    finally:
        db.cerrar_bd()
