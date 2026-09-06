from __future__ import annotations

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http import client_ip
from app.models.audit import AuditActionType, AuditLog
from app.models.patient import BiologicalSex
from app.models.user import User
from app.services.patient_access import load_accessible_patient


async def resolve_apply_female_bias(
    patient_id: UUID | None,
    patient_sex_override: BiologicalSex | None,
    current_user: User,
    db: AsyncSession,
    request: Request,
) -> bool:
    """Decide whether to apply the female-ADR risk multiplier, and audit any real PHI access.

    Shared by predict.py and explain.py. An explicit patient_sex override is a
    pure what-if simulation and never touches the DB.

    A patient_id goes through the same assignment-scoped check as the patients
    router (load_accessible_patient): a PATIENT reaches only their own record,
    a CLINICIAN only patients they're actively assigned to, and anything else
    is a 404. Without routing through that shared check, this would be a side
    door where any clinician could score any patient.
    """
    if patient_sex_override is not None:
        return patient_sex_override == BiologicalSex.FEMALE

    if patient_id is None:
        return False

    profile = await load_accessible_patient(patient_id, current_user, db)

    db.add(
        AuditLog(
            accessor_user_id=current_user.id,
            target_patient_id=profile.id,
            action_type=AuditActionType.VIEW,
            resource_type="PatientProfile",
            ip_address=client_ip(request),
        )
    )
    await db.commit()

    return profile.biological_sex == BiologicalSex.FEMALE
