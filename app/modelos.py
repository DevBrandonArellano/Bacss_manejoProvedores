"""Tablas de la base de datos."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import credito
from .db import Base

ADMINISTRADOR = "administrador"
CREADOR = "creador"
APROBADOR = "aprobador"
ROLES = {ADMINISTRADOR: "Administrador", CREADOR: "Creador", APROBADOR: "Aprobador"}

PENDIENTE = "pendiente"
APROBADO = "aprobado"
RECHAZADO = "rechazado"
ESTADOS_APROBACION = {PENDIENTE: "Pendiente", APROBADO: "Aprobado", RECHAZADO: "Rechazado"}

FACTURA_PENDIENTE = "pendiente"
FACTURA_PAGADA = "pagada"
FACTURA_ANULADA = "anulada"
ESTADOS_FACTURA = {FACTURA_PENDIENTE: "Pendiente", FACTURA_PAGADA: "Pagada", FACTURA_ANULADA: "Anulada"}


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    clave_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(20))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime)

    @property
    def rol_texto(self) -> str:
        return ROLES.get(self.rol, self.rol)

    @property
    def es_admin(self) -> bool:
        return self.rol == ADMINISTRADOR

    @property
    def puede_editar(self) -> bool:
        """Crear y modificar proveedores y facturas."""
        return self.rol in (ADMINISTRADOR, CREADOR)

    @property
    def puede_aprobar(self) -> bool:
        return self.rol in (ADMINISTRADOR, APROBADOR)


class TipoId(Base):
    __tablename__ = "tipos_id"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(10), unique=True)
    nombre: Mapped[str] = mapped_column(String(60))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class TipoCuenta(Base):
    __tablename__ = "tipos_cuenta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(10), unique=True)
    nombre: Mapped[str] = mapped_column(String(60))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Banco(Base):
    """Institución financiera. El código es el oficial (lo asigna el Estado): es texto y no se reformatea.

    En el catálogo oficial hay códigos compartidos por dos instituciones, así que
    la unicidad es sobre (codigo, nombre) y no sobre el código solo.
    """

    __tablename__ = "bancos"
    __table_args__ = (UniqueConstraint("codigo", "nombre", name="uq_banco_codigo_nombre"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    nombre_norm: Mapped[str] = mapped_column(String(200), index=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Proveedor(Base):
    __tablename__ = "proveedores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    nombre_norm: Mapped[str] = mapped_column(String(200), index=True)
    tipo_id_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tipos_id.id"), nullable=True)
    numero_id: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    tipo_cuenta_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tipos_cuenta.id"), nullable=True)
    numero_cuenta: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    banco_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bancos.id"), nullable=True)
    correo: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    credito_tipo: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    credito_valor: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    registrado_banco: Mapped[bool] = mapped_column(Boolean, default=False)
    notas: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    estado_aprobacion: Mapped[str] = mapped_column(String(20), default=PENDIENTE, index=True)
    aprobado_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    aprobado_en: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    motivo_rechazo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    creado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime)
    modificado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    modificado_en: Mapped[datetime] = mapped_column(DateTime)

    tipo_id: Mapped[Optional[TipoId]] = relationship(foreign_keys=[tipo_id_id])
    tipo_cuenta: Mapped[Optional[TipoCuenta]] = relationship(foreign_keys=[tipo_cuenta_id])
    banco: Mapped[Optional[Banco]] = relationship(foreign_keys=[banco_id])
    aprobado_por: Mapped[Optional[Usuario]] = relationship(foreign_keys=[aprobado_por_id])
    creado_por: Mapped[Usuario] = relationship(foreign_keys=[creado_por_id])
    modificado_por: Mapped[Usuario] = relationship(foreign_keys=[modificado_por_id])
    facturas: Mapped[List["Factura"]] = relationship(back_populates="proveedor")

    @property
    def credito_texto(self) -> str:
        return credito.texto(self.credito_tipo, self.credito_valor)

    @property
    def estado_texto(self) -> str:
        return ESTADOS_APROBACION.get(self.estado_aprobacion, self.estado_aprobacion)

    @property
    def aprobado(self) -> bool:
        return self.estado_aprobacion == APROBADO


class Factura(Base):
    __tablename__ = "facturas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    numero: Mapped[str] = mapped_column(String(60))
    fecha: Mapped[date] = mapped_column(Date)
    valor_centavos: Mapped[int] = mapped_column(Integer)
    moneda: Mapped[str] = mapped_column(String(3), default="USD")
    vencimiento: Mapped[date] = mapped_column(Date, index=True)
    estado: Mapped[str] = mapped_column(String(20), default=FACTURA_PENDIENTE, index=True)
    notas: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pagada_en: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    pagada_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    exportada_en: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    creado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime)

    proveedor: Mapped[Proveedor] = relationship(back_populates="facturas")
    pagada_por: Mapped[Optional[Usuario]] = relationship(foreign_keys=[pagada_por_id])
    creado_por: Mapped[Usuario] = relationship(foreign_keys=[creado_por_id])

    @property
    def valor(self) -> Decimal:
        return Decimal(self.valor_centavos) / Decimal(100)

    @property
    def estado_texto(self) -> str:
        return ESTADOS_FACTURA.get(self.estado, self.estado)


class Historial(Base):
    """Quién cambió qué y cuándo en un proveedor."""

    __tablename__ = "historial"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # creacion | cambio | estado | aprobacion | rechazo
    campo: Mapped[str] = mapped_column(String(60))
    valor_anterior: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    valor_nuevo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sensible: Mapped[bool] = mapped_column(Boolean, default=False)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    usuario_nombre: Mapped[str] = mapped_column(String(120))
    fecha: Mapped[datetime] = mapped_column(DateTime, index=True)

    proveedor: Mapped[Proveedor] = relationship(foreign_keys=[proveedor_id])


class Configuracion(Base):
    __tablename__ = "configuracion"

    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str] = mapped_column(Text, default="")
