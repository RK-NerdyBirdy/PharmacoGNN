from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.core.http import client_ip
from app.models.audit import AuditActionType, AuditLog
from app.models.patient import PatientCondition, PatientProfile, PatientRegimen
from app.models.user import User, UserRole
from app.schemas.patient import (
    PatientConditionCreate,
    PatientConditionRead,
    PatientConditionUpdate,
    PatientProfileCreate,
    PatientProfileCreateForUser,
    PatientProfileRead,
    PatientProfileUpdate,
    PatientRegimenCreate,
    PatientRegimenRead,
    PatientRegimenUpdate,
)

router = APIRouter(prefix="/patients", tags=["patients"])


def _audit(current_user: User, patient_id: UUID, action: AuditActionType, resource_type: str, request: Request) -> AuditLog:
    return AuditLog(
        accessor_user_id=current_user.id,
        target_patient_id=patient_id,
        action_type=action,
        resource_type=resource_type,
        ip_address=client_ip(request),
    )


async def _get_own_profile(current_user: User, db: AsyncSession) -> PatientProfile | None:
    return await db.scalar(select(PatientProfile).where(PatientProfile.user_id == current_user.id))


async def _get_authorized_profile(patient_id: UUID, current_user: User, db: AsyncSession) -> PatientProfile:
    """Loads a profile by id; a PATIENT may only load their own."""
    profile = await db.get(PatientProfile, patient_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")
    if current_user.role == UserRole.PATIENT and profile.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Patients may only access their own profile"
        )
    return profile


def _build_profile(payload: PatientProfileCreate, user_id: UUID) -> PatientProfile:
    return PatientProfile(
        user_id=user_id,
        legal_name=payload.legal_name,
        date_of_birth=payload.date_of_birth.isoformat(),
        medical_record_number=payload.medical_record_number,
        emergency_contact=payload.emergency_contact,
        biological_sex=payload.biological_sex,
        age=payload.age,
    )


def _apply_updates(obj: object, updates: dict) -> None:
    for field, value in updates.items():
        if field == "date_of_birth" and value is not None:
            value = value.isoformat()
        setattr(obj, field, value)


# --- Profile: self-service (PATIENT) ----------------------------------------


@router.post("/me", response_model=PatientProfileRead, status_code=status.HTTP_201_CREATED)
async def create_own_profile(
    payload: PatientProfileCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.PATIENT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientProfile:
    if await _get_own_profile(current_user, db) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile already exists")

    profile = _build_profile(payload, current_user.id)
    db.add(profile)
    await db.flush()
    db.add(_audit(current_user, profile.id, AuditActionType.CREATE, "PatientProfile", request))
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/me", response_model=PatientProfileRead)
async def read_own_profile(
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.PATIENT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientProfile:
    profile = await _get_own_profile(current_user, db)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    db.add(_audit(current_user, profile.id, AuditActionType.VIEW, "PatientProfile", request))
    await db.commit()
    return profile


# --- Profile: clinician-managed ----------------------------------------------


@router.post("", response_model=PatientProfileRead, status_code=status.HTTP_201_CREATED)
async def create_patient_profile(
    payload: PatientProfileCreateForUser,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientProfile:
    target_user = await db.get(User, payload.user_id)
    if target_user is None or target_user.role != UserRole.PATIENT:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No PATIENT-role user with that id")

    existing = await db.scalar(select(PatientProfile).where(PatientProfile.user_id == payload.user_id))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile already exists for this user")

    profile = _build_profile(payload, payload.user_id)
    db.add(profile)
    await db.flush()
    db.add(_audit(current_user, profile.id, AuditActionType.CREATE, "PatientProfile", request))
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/{patient_id}", response_model=PatientProfileRead)
async def read_patient_profile(
    patient_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientProfile:
    profile = await _get_authorized_profile(patient_id, current_user, db)
    db.add(_audit(current_user, profile.id, AuditActionType.VIEW, "PatientProfile", request))
    await db.commit()
    return profile


@router.patch("/{patient_id}", response_model=PatientProfileRead)
async def update_patient_profile(
    patient_id: UUID,
    payload: PatientProfileUpdate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientProfile:
    profile = await _get_authorized_profile(patient_id, current_user, db)
    _apply_updates(profile, payload.model_dump(exclude_unset=True))
    db.add(_audit(current_user, profile.id, AuditActionType.UPDATE, "PatientProfile", request))
    await db.commit()
    await db.refresh(profile)
    return profile


# --- Conditions (CLINICIAN writes; either role reads their own) -------------


@router.post(
    "/{patient_id}/conditions", response_model=PatientConditionRead, status_code=status.HTTP_201_CREATED
)
async def add_condition(
    patient_id: UUID,
    payload: PatientConditionCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientCondition:
    if await db.get(PatientProfile, patient_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")

    condition = PatientCondition(patient_id=patient_id, **payload.model_dump())
    db.add(condition)
    await db.flush()
    db.add(_audit(current_user, patient_id, AuditActionType.CREATE, "PatientCondition", request))
    await db.commit()
    await db.refresh(condition)
    return condition


@router.get("/{patient_id}/conditions", response_model=list[PatientConditionRead])
async def list_conditions(
    patient_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    active_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PatientCondition]:
    await _get_authorized_profile(patient_id, current_user, db)  # RBAC check; raises if unauthorized

    stmt = select(PatientCondition).where(PatientCondition.patient_id == patient_id)
    if active_only:
        stmt = stmt.where(PatientCondition.is_active.is_(True))
    stmt = stmt.order_by(PatientCondition.created_at.desc()).limit(limit).offset(offset)

    conditions = (await db.scalars(stmt)).all()
    db.add(_audit(current_user, patient_id, AuditActionType.VIEW, "PatientCondition", request))
    await db.commit()
    return list(conditions)


@router.patch("/{patient_id}/conditions/{condition_id}", response_model=PatientConditionRead)
async def update_condition(
    patient_id: UUID,
    condition_id: UUID,
    payload: PatientConditionUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientCondition:
    condition = await db.get(PatientCondition, condition_id)
    if condition is None or condition.patient_id != patient_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condition not found")

    _apply_updates(condition, payload.model_dump(exclude_unset=True))
    db.add(_audit(current_user, patient_id, AuditActionType.UPDATE, "PatientCondition", request))
    await db.commit()
    await db.refresh(condition)
    return condition


# --- Regimens (CLINICIAN writes; either role reads their own) ---------------


@router.post(
    "/{patient_id}/regimens", response_model=PatientRegimenRead, status_code=status.HTTP_201_CREATED
)
async def add_regimen(
    patient_id: UUID,
    payload: PatientRegimenCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientRegimen:
    if await db.get(PatientProfile, patient_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")

    regimen = PatientRegimen(patient_id=patient_id, prescriber_id=current_user.id, **payload.model_dump())
    db.add(regimen)
    await db.flush()
    db.add(_audit(current_user, patient_id, AuditActionType.CREATE, "PatientRegimen", request))
    await db.commit()
    await db.refresh(regimen)
    return regimen


@router.get("/{patient_id}/regimens", response_model=list[PatientRegimenRead])
async def list_regimens(
    patient_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    active_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PatientRegimen]:
    await _get_authorized_profile(patient_id, current_user, db)

    stmt = select(PatientRegimen).where(PatientRegimen.patient_id == patient_id)
    if active_only:
        stmt = stmt.where(PatientRegimen.end_date.is_(None))
    stmt = stmt.order_by(PatientRegimen.start_date.desc()).limit(limit).offset(offset)

    regimens = (await db.scalars(stmt)).all()
    db.add(_audit(current_user, patient_id, AuditActionType.VIEW, "PatientRegimen", request))
    await db.commit()
    return list(regimens)


@router.patch("/{patient_id}/regimens/{regimen_id}", response_model=PatientRegimenRead)
async def update_regimen(
    patient_id: UUID,
    regimen_id: UUID,
    payload: PatientRegimenUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientRegimen:
    regimen = await db.get(PatientRegimen, regimen_id)
    if regimen is None or regimen.patient_id != patient_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regimen not found")

    _apply_updates(regimen, payload.model_dump(exclude_unset=True))
    db.add(_audit(current_user, patient_id, AuditActionType.UPDATE, "PatientRegimen", request))
    await db.commit()
    await db.refresh(regimen)
    return regimen
