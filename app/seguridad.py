"""Contraseñas cifradas (Argon2) y freno a intentos repetidos de inicio de sesión."""
import time
from typing import Dict, List

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

_cifrador = PasswordHasher()

CLAVE_MINIMA = 8
MAX_INTENTOS = 5
BLOQUEO_SEGUNDOS = 300

_fallos: Dict[str, List[float]] = {}


def cifrar(clave: str) -> str:
    return _cifrador.hash(clave)


def verificar(clave_hash: str, clave: str) -> bool:
    try:
        return _cifrador.verify(clave_hash, clave)
    except (Argon2Error, InvalidHashError):
        return False


def error_clave(clave: str):
    """Mensaje de error si la contraseña no cumple el mínimo; None si es válida."""
    if len(clave or "") < CLAVE_MINIMA:
        return f"La contraseña debe tener al menos {CLAVE_MINIMA} caracteres."
    return None


def bloqueado(llave: str) -> bool:
    ahora = time.monotonic()
    recientes = [t for t in _fallos.get(llave, []) if ahora - t < BLOQUEO_SEGUNDOS]
    _fallos[llave] = recientes
    return len(recientes) >= MAX_INTENTOS


def registrar_fallo(llave: str) -> None:
    _fallos.setdefault(llave, []).append(time.monotonic())


def limpiar_fallos(llave: str = None) -> None:
    if llave is None:
        _fallos.clear()
    else:
        _fallos.pop(llave, None)
