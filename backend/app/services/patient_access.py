"""Who is allowed to touch which patient.

Single source of truth for patient-scoped authorization, shared by the
patients router and by the predict/explain paths (which resolve a patient_id
for demographic stratification and must be gated identically -- otherwise
"any clinician can score any patient" quietly survives as a side door).
"""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import PatientAssignment, PatientProfile
from app.models.user import User, UserRole

# Deliberately 404, never 403, for an unentitled clinician: a 403 would confirm
# that a patient with that id exists, which is itself a disclosure. The caller
# cannot distinguish "no such patient" from "not yours" -- that's the point.
_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")


def _active_assignment_filter(patient_id: UUID):
    return (
        PatientAssignment.patient_id == patient_id,
        PatientAssignment.ended_at.is_(None),
    )


async def is_assigned(patient_id: UUID, clinician_id: UUID, db: AsyncSession) -> bool:
    found = await db.scalar(
        select(PatientAssignment.id).where(
            *_active_assignment_filter(patient_id),
            PatientAssignment.clinician_id == clinician_id,
        )
    )
    return found is not None


async def list_active_assignments(patient_id: UUID, db: AsyncSession) -> list[PatientAssignment]:
    result = await db.scalars(
        select(PatientAssignment)
        .where(*_active_assignment_filter(patient_id))
        .order_by(PatientAssignment.is_primary.desc(), PatientAssignment.assigned_at.asc())
    )
    return list(result)


async def load_accessible_patient(
    patient_id: UUID, current_user: User, db: AsyncSession
) -> PatientProfile:
    """Load a profile the caller is entitled to, else 404.

    A PATIENT reaches only their own record. A CLINICIAN reaches only patients
    they hold an active assignment for -- holding the role is not enough.
    """
    profile = await db.get(PatientProfile, patient_id)
    if profile is None:
        raise _NOT_FOUND

    if current_user.role == UserRole.PATIENT:
        if profile.user_id != current_user.id:
            raise _NOT_FOUND
        return profile

    if not await is_assigned(patient_id, current_user.id, db):
        raise _NOT_FOUND
    return profile


async def assign_clinician(
    patient_id: UUID,
    clinician_id: UUID,
    db: AsyncSession,
    *,
    is_primary: bool = False,
) -> PatientAssignment:
    """Create an active assignment. Caller commits.

    Re-assigning an already-active pair is a no-op rather than an error, so
    repeated calls (e.g. a retried transfer) don't trip the partial unique
    index.
    """
    existing = await db.scalar(
        select(PatientAssignment).where(
            *_active_assignment_filter(patient_id),
            PatientAssignment.clinician_id == clinician_id,
        )
    )
    if existing is not None:
        return existing

    if is_primary:
        await _demote_current_primary(patient_id, db)

    assignment = PatientAssignment(
        patient_id=patient_id, clinician_id=clinician_id, is_primary=is_primary
    )
    db.add(assignment)
    await db.flush()
    return assignment


async def _demote_current_primary(patient_id: UUID, db: AsyncSession) -> None:
    current = await db.scalar(
        select(PatientAssignment).where(
            *_active_assignment_filter(patient_id),
            PatientAssignment.is_primary.is_(True),
        )
    )
    if current is not None:
        current.is_primary = False
        await db.flush()


async def end_assignment(
    patient_id: UUID, clinician_id: UUID, db: AsyncSession, *, reason: str
) -> PatientAssignment | None:
    """End an active assignment (never deletes the row). Caller commits."""
    assignment = await db.scalar(
        select(PatientAssignment).where(
            *_active_assignment_filter(patient_id),
            PatientAssignment.clinician_id == clinician_id,
        )
    )
    if assignment is None:
        return None

    assignment.ended_at = dt.datetime.now(dt.timezone.utc)
    assignment.ended_reason = reason
    await db.flush()
    return assignment
