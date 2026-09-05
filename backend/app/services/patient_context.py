from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditActionType, AuditLog
from app.models.patient import BiologicalSex, PatientProfile
from app.models.user import User, UserRole


async def resolve_apply_female_bias(
    patient_id: UUID | None,
    patient_sex_override: BiologicalSex | None,
    current_user: User,
    db: AsyncSession,
    request: Request,
) -> bool:
    """Decide whether to apply the female-ADR risk multiplier, and audit any real PHI access.

    Shared by predict.py and explain.py. An explicit patient_sex override is a pure
    what-if simulation and never touches the DB. A patient_id triggers an RBAC check
    (a PATIENT may only query their own profile; a CLINICIAN may query any) and writes
    an AuditLog VIEW entry, since it resolves a real patient's stored demographic data.
    """
    if patient_sex_override is not None:
        return patient_sex_override == BiologicalSex.FEMALE

    if patient_id is None:
        return False

    if current_user.role == UserRole.PATIENT:
        own_profile_id = await db.scalar(
            select(PatientProfile.id).where(PatientProfile.user_id == current_user.id)
        )
        if own_profile_id != patient_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Patients may only query their own profile"
            )

    profile = await db.get(PatientProfile, patient_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")

    db.add(
        AuditLog(
            accessor_user_id=current_user.id,
            target_patient_id=profile.id,
            action_type=AuditActionType.VIEW,
            resource_type="PatientProfile",
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()

    return profile.biological_sex == BiologicalSex.FEMALE
