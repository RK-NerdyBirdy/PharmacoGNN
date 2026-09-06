from __future__ import annotations

import datetime as dt
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.patient import PatientProfile
    from app.models.user import User


class ReportStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class InteractionReport(TimestampMixin, Base):
    """A frozen, point-in-time interaction analysis of a patient's active regimen.

    Generation is async (POST creates this row PENDING and returns immediately;
    a background task fills in `payload` and flips the status) because it can
    involve several LLM calls for the flagged high-risk pairs' explanations --
    see app/services/report_generation.py.

    `payload` holds the entire computed analysis body (model_status,
    regimen_snapshot, unresolved_drugs, summary, interaction_matrix, pairwise,
    substitutions, explanations) as one JSONB blob rather than a column per
    field: it's write-once, always read as a whole, and never queried on
    individual sub-fields, so a single column is simpler to evolve than a wide
    table. Unencrypted, same as PatientRegimen/PatientCondition -- clinical
    content in this codebase is not treated as identity-linking PHI the way
    legal_name/date_of_birth/medical_record_number are.

    The rendered PDF is NOT durable: it's written to local disk
    (settings.REPORTS_DIR / f"{id}.pdf") and `file_path` just records where.
    A missing file on disk (container restart/redeploy) is an expected,
    routine state -- see api/v1/reports.py, which regenerates it on demand
    from `payload` rather than failing.

    Soft-deleted via `deleted_at` (never hard-deleted) so "generate a report,
    delete it, the QR/link now revokes" doesn't lose the audit trail of the
    fact a report once existed for this patient.
    """

    __tablename__ = "interaction_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patient_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status", native_enum=True),
        nullable=False,
        default=ReportStatus.PENDING,
        index=True,
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    patient: Mapped["PatientProfile"] = relationship(back_populates="reports")
    generated_by_user: Mapped["User"] = relationship(foreign_keys=[generated_by])
