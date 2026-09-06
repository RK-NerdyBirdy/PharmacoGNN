from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.core.http import client_ip
from app.models.audit import AuditActionType, AuditLog
from app.models.patient import PatientAssignment, PatientCondition, PatientProfile, PatientRegimen
from app.models.user import User, UserRole
from app.schemas.patient import (
    PatientAccessEntry,
    PatientConditionCreate,
    PatientConditionRead,
    PatientConditionUpdate,
    PatientListItem,
    PatientOnboard,
    PatientOnboardResponse,
    PatientProfileCreate,
    PatientProfileRead,
    PatientProfileUpdate,
    PatientRegimenCreate,
    PatientRegimenRead,
    PatientRegimenUpdate,
    PatientSelfUpdate,
)
from app.schemas.prescription import (
    PrescriptionCreate,
    PrescriptionImportResponse,
    UnresolvedPrescriptionItem,
)
from app.services import invitations
from app.services.drug_resolution import resolve_drug
from app.services.patient_access import (
    assign_clinician,
    list_active_assignments,
    load_accessible_patient,
)

router = APIRouter(prefix="/patients", tags=["patients"])

# Status-code convention in this router:
#   * unassigned clinician touching any patient  -> 404 (never confirm the
#     patient exists; see services/patient_access.py)
#   * patient hitting a clinician-only *method*  -> 403 from require_role, since
#     the record isn't hidden from them (they can GET it), only the operation is.


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


# --- Patient's own record (read + narrow self-edit) --------------------------


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


@router.patch("/me", response_model=PatientProfileRead)
async def update_own_profile(
    payload: PatientSelfUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.PATIENT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientProfile:
    """Patients may correct their own demographics -- never clinical data.

    The allowed field set is enforced by PatientSelfUpdate's shape, so a
    clinical field sent here is rejected as an unknown field rather than
    silently ignored.
    """
    profile = await _get_own_profile(current_user, db)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    _apply_updates(profile, payload.model_dump(exclude_unset=True))
    db.add(_audit(current_user, profile.id, AuditActionType.UPDATE, "PatientProfile", request))
    await db.commit()
    await db.refresh(profile)
    return profile


# --- Clinician: roster -------------------------------------------------------


@router.get("", response_model=list[PatientListItem])
async def list_my_patients(
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PatientListItem]:
    """The requesting clinician's assigned patients.

    Note there is deliberately no name/MRN search parameter: those columns are
    encrypted at rest with a non-deterministic cipher, so the database cannot
    filter on them. Filtering has to happen client-side over a fetched page
    until someone adds a blind index.
    """
    active_regimens = (
        select(PatientRegimen.patient_id, func.count().label("regimen_count"))
        .where(PatientRegimen.end_date.is_(None))
        .group_by(PatientRegimen.patient_id)
        .subquery()
    )

    stmt = (
        select(
            PatientProfile,
            PatientAssignment,
            func.coalesce(active_regimens.c.regimen_count, 0),
            User.hashed_password.is_not(None),
        )
        .join(PatientAssignment, PatientAssignment.patient_id == PatientProfile.id)
        .join(User, User.id == PatientProfile.user_id)
        .outerjoin(active_regimens, active_regimens.c.patient_id == PatientProfile.id)
        .where(
            PatientAssignment.clinician_id == current_user.id,
            PatientAssignment.ended_at.is_(None),
        )
        .order_by(PatientAssignment.assigned_at.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = (await db.execute(stmt)).all()
    return [
        PatientListItem(
            id=profile.id,
            user_id=profile.user_id,
            legal_name=profile.legal_name,
            age=profile.age,
            biological_sex=profile.biological_sex,
            is_primary=assignment.is_primary,
            assigned_at=assignment.assigned_at,
            active_regimen_count=regimen_count,
            activation_status="active" if activated else "pending",
        )
        for profile, assignment, regimen_count, activated in rows
    ]


# --- Clinician: create / read / update a patient -----------------------------


@router.post("", response_model=PatientOnboardResponse, status_code=status.HTTP_201_CREATED)
async def onboard_patient(
    payload: PatientOnboard,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientOnboardResponse:
    """Create a patient end-to-end: account, profile, assignment, invite email.

    The account is created with no password; the emailed invite is the only
    thing that can set the first one.

    The database work is committed before the email is attempted, so a mail
    outage leaves a usable patient record plus a resend button rather than
    failing the clinician's operation outright.
    """
    existing_user = await db.scalar(select(User).where(User.email == payload.email))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=payload.email, hashed_password=None, role=UserRole.PATIENT)
    db.add(user)
    await db.flush()

    profile = _build_profile(payload, user.id)
    db.add(profile)
    await db.flush()

    # The creating clinician becomes the primary -- without this the patient
    # would be created and then immediately invisible to everyone.
    await assign_clinician(profile.id, current_user.id, db, is_primary=True)

    token = await invitations.issue_invitation(user.id, db, created_by=current_user.id)

    db.add(_audit(current_user, profile.id, AuditActionType.CREATE, "PatientProfile", request))
    db.add(_audit(current_user, profile.id, AuditActionType.CREATE, "PatientAssignment", request))
    await db.commit()
    await db.refresh(profile)

    email_status = await invitations.send_invite_email(payload.email, token, user.id, db)

    return PatientOnboardResponse(
        **PatientProfileRead.model_validate(profile).model_dump(),
        activation_status="pending",
        invite_email_status=email_status,
    )


@router.post("/{patient_id}/invite/resend", status_code=status.HTTP_200_OK)
async def resend_invite(
    patient_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Issue a fresh invite, invalidating any previous unused one."""
    profile = await load_accessible_patient(patient_id, current_user, db)

    user = await db.get(User, profile.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient account not found")
    if user.is_activated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Account is already activated"
        )

    token = await invitations.issue_invitation(user.id, db, created_by=current_user.id)
    db.add(_audit(current_user, profile.id, AuditActionType.CREATE, "UserInvitation", request))
    await db.commit()

    email_status = await invitations.send_invite_email(user.email, token, user.id, db)
    return {"invite_email_status": email_status}


@router.get("/{patient_id}", response_model=PatientProfileRead)
async def read_patient_profile(
    patient_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientProfile:
    profile = await load_accessible_patient(patient_id, current_user, db)
    db.add(_audit(current_user, profile.id, AuditActionType.VIEW, "PatientProfile", request))
    await db.commit()
    return profile


@router.patch("/{patient_id}", response_model=PatientProfileRead)
async def update_patient_profile(
    patient_id: UUID,
    payload: PatientProfileUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientProfile:
    profile = await load_accessible_patient(patient_id, current_user, db)
    _apply_updates(profile, payload.model_dump(exclude_unset=True))
    db.add(_audit(current_user, profile.id, AuditActionType.UPDATE, "PatientProfile", request))
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/{patient_id}/access", response_model=list[PatientAccessEntry])
async def list_patient_access(
    patient_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PatientAccessEntry]:
    """Who currently holds access to this record.

    Readable by the patient themselves (so they can see who can see them) and
    by any clinician already assigned to them.
    """
    await load_accessible_patient(patient_id, current_user, db)
    assignments = await list_active_assignments(patient_id, db)

    clinician_ids = [a.clinician_id for a in assignments]
    emails = dict(
        (await db.execute(select(User.id, User.email).where(User.id.in_(clinician_ids)))).all()
    ) if clinician_ids else {}

    db.add(_audit(current_user, patient_id, AuditActionType.VIEW, "PatientAssignment", request))
    await db.commit()

    return [
        PatientAccessEntry(
            clinician_id=a.clinician_id,
            clinician_email=emails.get(a.clinician_id, ""),
            is_primary=a.is_primary,
            assigned_at=a.assigned_at,
        )
        for a in assignments
    ]


# --- Conditions (CLINICIAN writes; patient reads own) ------------------------


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
    await load_accessible_patient(patient_id, current_user, db)

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
    await load_accessible_patient(patient_id, current_user, db)

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
    await load_accessible_patient(patient_id, current_user, db)

    condition = await db.get(PatientCondition, condition_id)
    if condition is None or condition.patient_id != patient_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condition not found")

    _apply_updates(condition, payload.model_dump(exclude_unset=True))
    db.add(_audit(current_user, patient_id, AuditActionType.UPDATE, "PatientCondition", request))
    await db.commit()
    await db.refresh(condition)
    return condition


# --- Regimens (CLINICIAN writes; patient reads own) --------------------------


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
    """Add one drug. Same resolution rule as prescription import: an
    unresolvable drug is rejected outright (422), never stored as-is --
    there's no "unresolved" list to report into here since it's a single item.
    """
    await load_accessible_patient(patient_id, current_user, db)

    resolution = resolve_drug(payload.drug_name, payload.pubchem_cid)
    if not resolution.resolved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not resolve drug '{payload.drug_name}': {resolution.reason}",
        )

    regimen = PatientRegimen(
        patient_id=patient_id,
        prescriber_id=current_user.id,
        pubchem_cid=resolution.cid,
        drug_name=resolution.name,
        dosage=payload.dosage,
        start_date=payload.start_date,
    )
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
    await load_accessible_patient(patient_id, current_user, db)

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
    await load_accessible_patient(patient_id, current_user, db)

    regimen = await db.get(PatientRegimen, regimen_id)
    if regimen is None or regimen.patient_id != patient_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regimen not found")

    _apply_updates(regimen, payload.model_dump(exclude_unset=True))
    db.add(_audit(current_user, patient_id, AuditActionType.UPDATE, "PatientRegimen", request))
    await db.commit()
    await db.refresh(regimen)
    return regimen


@router.delete("/{patient_id}/regimens/{regimen_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_regimen(
    patient_id: UUID,
    regimen_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Hard delete -- erases the row. For correcting a data-entry mistake only.

    To stop a medication that was genuinely taken, PATCH end_date instead:
    that preserves history, which is what "discontinued" should mean for a
    medical record. This endpoint exists for "this was entered in error and
    should never have existed", which is a different, rarer operation and
    deliberately looks different in the API (DELETE vs PATCH) so a client
    can't reach for it by habit.
    """
    await load_accessible_patient(patient_id, current_user, db)

    regimen = await db.get(PatientRegimen, regimen_id)
    if regimen is None or regimen.patient_id != patient_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regimen not found")

    db.add(_audit(current_user, patient_id, AuditActionType.DELETE, "PatientRegimen", request))
    await db.delete(regimen)
    await db.commit()


# --- Prescriptions (structured multi-drug import) ----------------------------


@router.post(
    "/{patient_id}/prescriptions",
    response_model=PrescriptionImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_prescription(
    patient_id: UUID,
    payload: PrescriptionCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PrescriptionImportResponse:
    """Create regimen rows from a structured prescription in one call.

    Every item is resolved against the model's vocabulary before anything is
    written. With allow_partial=False (the default), any single unresolved
    item aborts the whole import -- committing the resolvable ones anyway
    would leave a regimen record that looks complete but silently omits a
    drug the model can't score, which makes every future interaction report
    on this patient falsely reassuring. allow_partial=True accepts that
    trade-off explicitly when the caller has a reason to.
    """
    await load_accessible_patient(patient_id, current_user, db)

    resolutions = [(item, resolve_drug(item.drug_name, item.pubchem_cid)) for item in payload.items]
    unresolved = [
        UnresolvedPrescriptionItem(
            drug_name=item.drug_name, pubchem_cid=item.pubchem_cid, reason=resolution.reason
        )
        for item, resolution in resolutions
        if not resolution.resolved
    ]
    resolved = [(item, resolution) for item, resolution in resolutions if resolution.resolved]

    if unresolved and not payload.allow_partial:
        return PrescriptionImportResponse(created=[], unresolved=unresolved, committed=False)

    batch_id = uuid4()
    rows = [
        PatientRegimen(
            patient_id=patient_id,
            prescriber_id=current_user.id,
            pubchem_cid=resolution.cid,
            drug_name=resolution.name,
            dosage=item.dosage,
            start_date=item.start_date,
            end_date=item.end_date,
            external_prescriber_name=payload.prescriber_name,
            import_batch_id=batch_id,
        )
        for item, resolution in resolved
    ]
    for row in rows:
        db.add(row)

    if rows:
        await db.flush()
        db.add(_audit(current_user, patient_id, AuditActionType.CREATE, "PatientRegimen", request))
        await db.commit()
        for row in rows:
            await db.refresh(row)

    return PrescriptionImportResponse(
        created=[PatientRegimenRead.model_validate(row) for row in rows],
        unresolved=unresolved,
        committed=bool(rows),
    )
