from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.patient import PatientProfile


class UserRole(str, enum.Enum):
    CLINICIAN = "CLINICIAN"
    PATIENT = "PATIENT"


class User(TimestampMixin, Base):
    """Login identity + RBAC role. PHI lives on PatientProfile, not here."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # NULL until the account is activated. A clinician-created patient exists
    # with no password at all -- the emailed invite token is the only thing
    # that can set the first one, so there is never a password in transit.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    patient_profile: Mapped["PatientProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def is_activated(self) -> bool:
        """Whether a password has ever been set.

        Distinct from is_active, which is the separate "enabled/disabled by an
        administrator" axis -- a never-activated account and a suspended one
        are different states and shouldn't share a flag.
        """
        return self.hashed_password is not None
