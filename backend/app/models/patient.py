from __future__ import annotations

import datetime as dt
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, EncryptedString, EncryptedText, TimestampMixin

if TYPE_CHECKING:
    from app.models.audit import AuditLog
    from app.models.report import InteractionReport
    from app.models.user import User


class BiologicalSex(str, enum.Enum):
    FEMALE = "FEMALE"
    MALE = "MALE"
    INTERSEX = "INTERSEX"


class PatientProfile(TimestampMixin, Base):
    """One-to-one PHI record for a PATIENT-role user.

    legal_name / date_of_birth / medical_record_number / emergency_contact are
    encrypted at rest (see app.db.base.EncryptedString/EncryptedText) and are
    therefore NOT queryable or unique-constrainable at the DB level — see the
    note in app.core.security on blind indexes if that's ever needed.

    biological_sex and age are kept as clean, indexed columns on purpose:
    Phase 2's GNN inference path needs to filter/stratify on them in bulk
    without decrypting a row per lookup.
    """

    __tablename__ = "patient_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # --- Encrypted at rest (AES-256-GCM via app.core.security) ---
    legal_name: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    date_of_birth: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    medical_record_number: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    emergency_contact: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)

    # --- Clean, indexed demographic columns ---
    biological_sex: Mapped[BiologicalSex] = mapped_column(
        Enum(BiologicalSex, name="biological_sex", native_enum=True), nullable=False, index=True
    )
    age: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    user: Mapped["User"] = relationship(back_populates="patient_profile")
    assignments: Mapped[list["PatientAssignment"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    conditions: Mapped[list["PatientCondition"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    regimens: Mapped[list["PatientRegimen"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    reports: Mapped[list["InteractionReport"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="target_patient")


class PatientAssignment(TimestampMixin, Base):
    """Which clinician(s) currently have authority over a patient.

    Access to a patient is granted by an active row here -- NOT by holding the
    CLINICIAN role. A clinician with no active assignment to a patient cannot
    see that patient at all (and gets a 404, not a 403, so the API doesn't
    leak that the patient exists).

    Multiple active assignments per patient are legal by design: a transfer
    grants the receiving clinician access without immediately revoking the
    sending clinician's, so both hold access during the handover window.
    Exactly one active assignment per patient is is_primary.

    Rows are ended (ended_at set), never deleted, so "who was entitled to see
    this record on date X" stays answerable after a transfer.
    """

    __tablename__ = "patient_assignments"
    __table_args__ = (
        # At most one live assignment per (patient, clinician) pair.
        Index(
            "uq_patient_assignments_active_pair",
            "patient_id",
            "clinician_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        # At most one live *primary* clinician per patient.
        Index(
            "uq_patient_assignments_active_primary",
            "patient_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL AND is_primary"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patient_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assigned_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    ended_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    patient: Mapped["PatientProfile"] = relationship(back_populates="assignments")
    clinician: Mapped["User"] = relationship(foreign_keys=[clinician_id])


class PatientCondition(TimestampMixin, Base):
    """Diagnosed condition used for drug-disease collision screening (Phase 2).

    Deliberately NOT field-encrypted like PatientProfile's columns: Phase 2
    cross-references condition_name against active regimens in bulk, which
    isn't feasible against non-deterministic ciphertext. Access is instead
    protected by RBAC + the AuditLog trail on the parent patient profile.
    """

    __tablename__ = "patient_conditions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patient_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    condition_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    icd10_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    diagnosed_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    patient: Mapped["PatientProfile"] = relationship(back_populates="conditions")


class PatientRegimen(TimestampMixin, Base):
    """One prescribed compound in a patient's drug cart.

    end_date IS NULL means the medication is currently active; Phase 2's
    regimen-matrix endpoint operates over the set of rows where end_date is
    null (or in the future).

    Discontinuing (PATCH .../regimens/{id} with end_date) is the normal way
    a medication stops -- it preserves history. Hard-deleting the row is a
    separate, narrower operation for correcting data-entry mistakes only.
    """

    __tablename__ = "patient_regimens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patient_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stored in the exact "CID" + 9-digit zero-padded form used as keys in
    # gnn_engine.DRUG2IDX (e.g. "CID000002244"), NOT a bare integer -- a row
    # here has to be usable as /predict/regimen input with zero conversion.
    # Every write path (manual add, prescription import) resolves through
    # services/drug_resolution.py to guarantee that; nothing writes an
    # unvalidated CID.
    pubchem_cid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    drug_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dosage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    prescriber_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Free text: who actually wrote the prescription, when that's someone
    # outside this system. Distinct from prescriber_id, which stays the
    # accountable system user (who entered this row), and is never displayed
    # as if it were the origin of an externally-written prescription.
    external_prescriber_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Shared by every row created from the same POST .../prescriptions call,
    # so "everything from this one prescription" stays answerable. NULL for
    # rows added via the single-drug manual-add endpoint.
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    patient: Mapped["PatientProfile"] = relationship(back_populates="regimens")
    prescriber: Mapped["User | None"] = relationship(foreign_keys=[prescriber_id])
