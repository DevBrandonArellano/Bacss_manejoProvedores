"""Validación de cédula y RUC de Ecuador (dígito verificador).

Reglas, contrastadas con la implementación de referencia de python-stdnum (stdnum/ec/ci.py y ruc.py):

- Cédula (10 dígitos): provincia 01-24 (también 30 y 50), tercer dígito 0-6 y dígito verificador por
  módulo 10 (coeficientes 2,1,2,1,… y se resta 9 a los productos mayores que 9).
- RUC de persona natural (tercer dígito 0-5): una cédula válida + establecimiento distinto de 000.
- RUC de sociedad privada (tercer dígito 9) y pública (tercer dígito 6): módulo 11 con coeficientes
  4,3,2,7,6,5,4,3,2,1 (privada) y 3,2,7,6,5,4,3,2,1 (pública).

Qué bloquea y qué solo avisa:
- La cédula y el RUC de persona natural son seguros: un error es un ERROR y no se puede guardar.
- En los RUC de sociedades el módulo 11 no está garantizado por el SRI y se han reportado RUC reales que no
  lo cumplen; por eso allí todo problema es un AVISO: se puede guardar y queda marcado en «Validaciones».
"""
from dataclasses import dataclass, field
from typing import List

PROVINCIAS = {f"{n:02d}" for n in range(1, 25)} | {"30", "50"}
COEF_PRIVADA = (4, 3, 2, 7, 6, 5, 4, 3, 2, 1)
COEF_PUBLICA = (3, 2, 7, 6, 5, 4, 3, 2, 1)


@dataclass
class Revision:
    errores: List[str] = field(default_factory=list)  # impiden guardar
    avisos: List[str] = field(default_factory=list)  # se puede guardar, pero conviene confirmarlo


def _modulo10(digitos: str) -> bool:
    """True si los 10 dígitos de una cédula cumplen el módulo 10."""
    total = 0
    for i, c in enumerate(digitos):
        producto = int(c) * (2 if i % 2 == 0 else 1)
        total += producto - 9 if producto > 9 else producto
    return total % 10 == 0


def _modulo11(digitos: str, coeficientes) -> bool:
    return sum(int(c) * k for c, k in zip(digitos, coeficientes)) % 11 == 0


def _problemas_cedula(numero: str) -> List[str]:
    """Problemas de una cédula de 10 dígitos (lista vacía si es válida)."""
    if numero[:2] not in PROVINCIAS:
        return ["Los dos primeros dígitos (provincia) no son válidos."]
    if numero[2] > "6":
        return ["El tercer dígito de una cédula no puede ser mayor que 6."]
    if not _modulo10(numero):
        return ["El dígito verificador no coincide: revise si falta o sobra un número, o si hay dos intercambiados."]
    return []


def revisar_cedula(numero: str) -> Revision:
    if not (numero.isdigit() and len(numero) == 10):
        return Revision(errores=["Una cédula debe tener 10 dígitos."])
    return Revision(errores=_problemas_cedula(numero))


def revisar_ruc(numero: str) -> Revision:
    if not (numero.isdigit() and len(numero) == 13):
        return Revision(errores=["Un RUC debe tener 13 dígitos."])
    tercero = numero[2]
    if tercero <= "5":  # persona natural: la base es una cédula
        errores = [f"El RUC de persona natural debe empezar con una cédula válida. {p}" for p in _problemas_cedula(numero[:10])]
        if numero[10:] == "000":
            errores.append("Los tres últimos dígitos (establecimiento) no pueden ser 000.")
        return Revision(errores=errores)

    # Sociedades: solo avisos (el SRI no garantiza este cálculo para todos los RUC).
    avisos = []
    if tercero == "9":
        tipo, coef, ceros = "sociedad privada", COEF_PRIVADA, "000"
    elif tercero == "6":
        tipo, coef, ceros = "entidad pública", COEF_PUBLICA, "0000"
    else:
        return Revision(avisos=[f"El tercer dígito ({tercero}) no corresponde a un tipo de RUC conocido (0-5, 6 o 9)."])
    if numero[:2] not in PROVINCIAS:
        avisos.append(f"RUC de {tipo}: los dos primeros dígitos (provincia) no son los habituales.")
    if numero[-len(ceros):] == ceros:
        avisos.append(f"RUC de {tipo}: el número de establecimiento no puede ser {ceros}.")
    if not _modulo11(numero[: len(coef)], coef):
        avisos.append(
            f"RUC de {tipo}: el dígito verificador no coincide con el cálculo habitual (módulo 11). "
            "Puede ser correcto, porque el SRI no lo garantiza para sociedades: confírmelo en el SRI."
        )
    return Revision(avisos=avisos)


def revisar(codigo_tipo: str, numero: str) -> Revision:
    """Revisa un número según el código del tipo de ID (C = cédula, R = RUC; otros tipos no se revisan)."""
    numero = (numero or "").strip()
    if codigo_tipo == "C":
        return revisar_cedula(numero)
    if codigo_tipo == "R":
        return revisar_ruc(numero)
    return Revision()
