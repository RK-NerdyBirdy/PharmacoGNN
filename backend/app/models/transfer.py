from __future__ import annotations

import datetime as dt
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.patient import PatientProfile
    from app.models.user import User


class TransferStatus(str, enum.Enum):
    PENDING_PATIENT_CONSENT = "PENDING_PATIENT_CONSENT"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    LOCKED = "LOCKED"


class PatientTransfer(TimestampMixin, Base):
    """A request to share a patient's record with another clinician, gated on the patient's OTP consent.

    Per the agreed design, the receiving clinician never has to accept, and
    the initiating clinician never loses access -- approval just adds a
    second, simultaneous active PatientAssignment (see
    services/patient_access.assign_clinician); it never ends the first.
    "Transfer" names the feature, not the mechanics: nothing is actually
    taken away from anyone.

    otp_hash is SHA-256, same reasoning as UserInvitation.token_hash: only
    the hash is stored, so a database leak can't hand over a live code. The
    plaintext exists only in the one email sent to the patient.

    Only one PENDING_PATIENT_CONSENT transfer may exist per patient at a time
    (the partial unique index below) -- a second POST while one is open
    returns 409 rather than racing two consent flows for the same patient.
    """

    __tablename__ = "patient_transfers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    to_clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[TransferStatus] = mapped_column(
        Enum(TransferStatus, name="transfer_status", native_enum=True),
        nullable=False,
        default=TransferStatus.PENDING_PATIENT_CONSENT,
        index=True,
    )
    otp_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    otp_expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    consented_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["PatientProfile"] = relationship(back_populates="transfers")
    from_clinician: Mapped["User"] = relationship(foreign_keys=[from_clinician_id])
    to_clinician: Mapped["User"] = relationship(foreign_keys=[to_clinician_id])

    __table_args__ = (
        Index(
            "uq_patient_transfers_one_pending",
            "patient_id",
            unique=True,
            postgresql_where=text("status = 'PENDING_PATIENT_CONSENT'"),
        ),
    )
