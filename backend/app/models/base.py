"""Patrones comunes a todos los modelos (Capítulo 5, Apéndice A).

- Auditoría en origen: created_at, updated_at y created_by en cada tabla.
- Borrado lógico en datos de negocio: is_active + deleted_at, nunca DELETE.

Los valores por defecto de fecha son *funciones* (utcnow), no llamadas: si se
escribiera ``default=datetime.now(timezone.utc)`` la fecha se calcularía una sola
vez al importar el módulo y todas las filas compartirían la misma marca de tiempo.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, select, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


def utcnow() -> datetime:
    """Fecha y hora actual en UTC, sin zona (MySQL DATETIME no guarda zona)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class AuditMixin(TimestampMixin):
    # Id de platform_core.users. Sin clave foránea porque los usuarios viven en
    # otro esquema y SQLAlchemy no relaciona tablas de binds distintos (ADR-008).
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SoftDeleteMixin:
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def soft_delete(self) -> None:
        self.is_active = False
        self.deleted_at = utcnow()

    def restore(self) -> None:
        self.is_active = True
        self.deleted_at = None

    @classmethod
    def select_active(cls):
        """``select()`` que excluye las filas borradas lógicamente."""
        return select(cls).where(cls.is_active.is_(True))


class BusinessMixin(AuditMixin, SoftDeleteMixin):
    """Datos de negocio: auditoría completa y borrado lógico."""


class VersionedMixin:
    """Bloqueo optimista (Capítulo 7): cada UPDATE incrementa ``row_version``.

    La API devuelve la versión al leer y la exige al modificar; si otra persona
    guardó antes, la versión ya no coincide y se responde 409 en lugar de
    sobrescribir sus cambios sin avisar. SQLAlchemy además comprueba la versión
    en el propio UPDATE, así que dos escrituras simultáneas tampoco se pisan.
    """

    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))

    @declared_attr.directive
    def __mapper_args__(cls):
        return {"version_id_col": cls.row_version}
