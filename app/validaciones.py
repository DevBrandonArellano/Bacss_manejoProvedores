"""Avisos de proveedores con datos incompletos o sospechosos."""
from collections import defaultdict
from typing import Dict, List

from sqlalchemy import select

from .modelos import Proveedor
from .servicios import LARGO_ID, correo_valido, partes_correo

CORREO_COMPARTIDO_DESDE = 3  # a partir de cuántos proveedores con el mismo correo se avisa

GRUPOS = [
    ("cuenta_duplicada", "Misma cuenta bancaria en más de un proveedor", "alta"),
    ("id_duplicado", "Identificación repetida", "alta"),
    ("sin_cuenta", "Sin número o tipo de cuenta", "alta"),
    ("sin_banco", "Sin banco", "alta"),
    ("sin_id", "Sin identificación", "media"),
    ("largo_id", "Número de ID que no corresponde al tipo", "media"),
    ("correo_malo", "Correo mal formado", "media"),
    ("sin_correo", "Sin correo", "baja"),
    ("correo_compartido", "Mismo correo en varios proveedores", "baja"),
    ("sin_credito", "Sin condición de crédito", "baja"),
    ("nombre_duplicado", "Nombre repetido", "baja"),
]


def revisar(db, incluir_inactivos: bool = False) -> List[dict]:
    """Lista de grupos {clave, titulo, severidad, casos:[{proveedor, detalle}]} con al menos un caso."""
    consulta = select(Proveedor).order_by(Proveedor.nombre_norm)
    if not incluir_inactivos:
        consulta = consulta.where(Proveedor.activo.is_(True))
    proveedores = db.scalars(consulta).all()

    casos: Dict[str, list] = defaultdict(list)
    por_cuenta, por_id, por_correo, por_nombre = (defaultdict(list) for _ in range(4))

    for p in proveedores:
        if not p.numero_cuenta or p.tipo_cuenta_id is None:
            casos["sin_cuenta"].append((p, "Falta el número o el tipo de cuenta."))
        else:
            por_cuenta[p.numero_cuenta].append(p)
        if p.banco_id is None:
            casos["sin_banco"].append((p, "No tiene banco asignado."))
        if not p.numero_id or p.tipo_id_id is None:
            casos["sin_id"].append((p, "Falta el tipo o el número de ID."))
        else:
            por_id[(p.tipo_id_id, p.numero_id)].append(p)
            largo = LARGO_ID.get(p.tipo_id.codigo) if p.tipo_id else None
            if largo and not (p.numero_id.isdigit() and len(p.numero_id) == largo):
                casos["largo_id"].append(
                    (p, f"{p.tipo_id.nombre} debe tener {largo} dígitos y tiene {len(p.numero_id)} caracteres.")
                )
        if not p.correo:
            casos["sin_correo"].append((p, "No tiene correo."))
        else:
            if not correo_valido(p.correo):
                casos["correo_malo"].append((p, "El correo no tiene un formato válido."))
            for parte in partes_correo(p.correo):
                por_correo[parte.lower()].append(p)
        if not p.credito_tipo:
            casos["sin_credito"].append((p, "Sus facturas se tratarán como de contado."))
        por_nombre[p.nombre_norm].append(p)

    for cuenta, lista in por_cuenta.items():
        if len(lista) > 1:
            for p in lista:
                otros = ", ".join(o.nombre for o in lista if o.id != p.id)
                casos["cuenta_duplicada"].append((p, f"Comparte la cuenta terminada en {cuenta[-4:]} con: {otros}."))
    for _clave, lista in por_id.items():
        if len(lista) > 1:
            for p in lista:
                otros = ", ".join(o.nombre for o in lista if o.id != p.id)
                casos["id_duplicado"].append((p, f"Misma identificación que: {otros}."))
    for correo, lista in por_correo.items():
        unicos = {p.id: p for p in lista}
        if len(unicos) >= CORREO_COMPARTIDO_DESDE:
            for p in unicos.values():
                casos["correo_compartido"].append((p, f"{correo} está en {len(unicos)} proveedores."))
    for _nombre, lista in por_nombre.items():
        if len(lista) > 1:
            for p in lista:
                casos["nombre_duplicado"].append((p, f"Hay {len(lista)} proveedores con este nombre."))

    grupos = []
    for clave, titulo, severidad in GRUPOS:
        if casos[clave]:
            grupos.append(
                {
                    "clave": clave,
                    "titulo": titulo,
                    "severidad": severidad,
                    "casos": [{"proveedor": p, "detalle": d} for p, d in casos[clave]],
                }
            )
    return grupos


def avisos_de(db, proveedor: Proveedor) -> List[dict]:
    """Avisos que afectan a un proveedor concreto (para su ficha y para quien aprueba)."""
    avisos = []
    for grupo in revisar(db, incluir_inactivos=not proveedor.activo):
        for item in grupo["casos"]:
            if item["proveedor"].id == proveedor.id:
                avisos.append({"titulo": grupo["titulo"], "severidad": grupo["severidad"], "detalle": item["detalle"]})
    return avisos
