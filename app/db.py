"""Conexión a SQLite."""
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = None


def iniciar_bd(ruta) -> None:
    """Abre (o crea) la base de datos y sus tablas."""
    global engine, SessionLocal
    cerrar_bd()
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{ruta.as_posix()}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(conexion, _registro):  # pragma: no cover - configuración del motor
        cursor = conexion.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    from . import modelos  # noqa: F401  (registra las tablas)

    Base.metadata.create_all(engine)
    _agregar_columnas_faltantes()


# Columnas añadidas después de la primera versión: create_all no las agrega a tablas que ya existen.
COLUMNAS_NUEVAS = (
    ("usuarios", "empresa_id", "INTEGER REFERENCES empresas(id)"),
    ("historial", "empresa_id", "INTEGER REFERENCES empresas(id)"),
)


def _agregar_columnas_faltantes() -> None:
    """Actualiza bases creadas con versiones anteriores sin perder datos."""
    inspector = inspect(engine)
    with engine.begin() as conexion:
        for tabla, columna, definicion in COLUMNAS_NUEVAS:
            if tabla not in inspector.get_table_names():
                continue
            if columna not in {c["name"] for c in inspector.get_columns(tabla)}:
                conexion.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}"))
                if tabla == "historial":
                    conexion.execute(text("CREATE INDEX IF NOT EXISTS ix_historial_empresa_id ON historial(empresa_id)"))


def cerrar_bd() -> None:
    global engine, SessionLocal
    if engine is not None:
        engine.dispose()
    engine = None
    SessionLocal = None


def get_db():
    sesion = SessionLocal()
    try:
        yield sesion
    finally:
        sesion.close()
