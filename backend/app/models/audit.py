from __future__ import annotations

import datetime as dt
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.patient import PatientProfile
    from app.models.user import User


class AuditActionType(str, enum.Enum):
    VIEW = "VIEW"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    EXPORT = "EXPORT"
    LOGIN = "LOGIN"


class AuditLog(Base):
    """Append-only ledger of every access to a patient's decrypted PHI.

    Immutability is enforced at two layers: this model has no updated_at
    column and no update/delete path is ever wired up in application code,
    AND the initial Alembic migration installs a BEFORE UPDATE/DELETE
    trigger on this table that raises, so even a raw SQL session or a
    compromised app credential cannot alter or remove a row.

    accessor_user_id / target_patient_id use ondelete="RESTRICT" so a user
    or patient profile can never be hard-deleted out from under its own
    audit trail.

    id is a UUID (not a sequential BIGINT) for two reasons: consistency with
    every other PK in the schema, and because a monotonically increasing
    integer PK leaks the total access-event volume (and roughly the rate of
    growth) to anyone who can see two id values, which is exactly the kind
    of side channel a privacy-first audit trail shouldn't expose.
    accessor_user_id is explicitly indexed so "all actions by accessor X" is
    an index lookup, not a sequential scan, as the table grows into the
    millions of rows.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    accessor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patient_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action_type: Mapped[AuditActionType] = mapped_column(
        Enum(AuditActionType, name="audit_action_type", native_enum=True), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    accessor: Mapped["User"] = relationship(foreign_keys=[accessor_user_id])
    target_patient: Mapped["PatientProfile"] = relationship(back_populates="audit_logs")
