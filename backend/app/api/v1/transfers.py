from __future__ import annotations

import datetime as dt
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.core.config import settings
from app.core.http import client_ip
from app.core.rate_limit import limiter
from app.models.audit import AuditActionType, AuditLog
from app.models.patient import PatientProfile
from app.models.transfer import PatientTransfer, TransferStatus
from app.models.user import User, UserRole
from app.schemas.transfer import ClinicianRef, TransferConsent, TransferCreate, TransferRead
from app.services import transfers as transfer_otp
from app.services.patient_access import assign_clinician, is_assigned, load_accessible_patient

router = APIRouter(tags=["transfers"])

# Cancellable/resendable/declinable states -- everything short of a terminal
# outcome (approved/declined/cancelled). LOCKED is included because running
# out of OTP attempts is a recoverable dead end (resend) or something the
# patient/clinician can still explicitly close out (decline/cancel), not a
# permanent decision the way declining or cancelling is.
_OPEN_STATUSES = (TransferStatus.PENDING_PATIENT_CONSENT, TransferStatus.LOCKED)


def _audit(current_user: User, patient_id: UUID, action: AuditActionType, request: Request) -> AuditLog:
    return AuditLog(
        accessor_user_id=current_user.id,
        target_patient_id=patient_id,
        action_type=action,
        resource_type="PatientTransfer",
        ip_address=client_ip(request),
    )


async def _load_transfer_or_404(transfer_id: UUID, db: AsyncSession) -> PatientTransfer:
    transfer = await db.get(PatientTransfer, transfer_id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    return transfer


async def _require_participant(transfer: PatientTransfer, current_user: User, db: AsyncSession) -> None:
    """404s (never 403) for anyone who isn't a party to this transfer.

    Participants: the initiating clinician, the receiving clinician, or the
    patient themself. Anyone else gets the same 404 an unassigned clinician
    gets elsewhere in this API -- existence isn't confirmed to a non-party.
    """
    if current_user.role == UserRole.CLINICIAN:
        if current_user.id in (transfer.from_clinician_id, transfer.to_clinician_id):
            return
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")

    profile = await db.get(PatientProfile, transfer.patient_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")


async def _require_patient(transfer: PatientTransfer, current_user: User, db: AsyncSession) -> None:
    """404s for anyone but the specific patient this transfer concerns."""
    profile = await db.get(PatientProfile, transfer.patient_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")


async def _build_read(transfer: PatientTransfer, db: AsyncSession) -> TransferRead:
    from_clinician = await db.get(User, transfer.from_clinician_id)
    to_clinician = await db.get(User, transfer.to_clinician_id)
    return TransferRead(
        id=transfer.id,
        patient_id=transfer.patient_id,
        from_clinician=ClinicianRef(id=from_clinician.id, email=from_clinician.email),
        to_clinician=ClinicianRef(id=to_clinician.id, email=to_clinician.email),
        status=transfer.status.value.lower(),
        otp_expires_at=transfer.otp_expires_at,
        attempts_remaining=transfer.attempts_remaining,
        created_at=transfer.created_at,
        consented_at=transfer.consented_at,
    )


@router.post(
    "/patients/{patient_id}/transfers", response_model=TransferRead, status_code=status.HTTP_201_CREATED
)
async def create_transfer(
    patient_id: UUID,
    payload: TransferCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TransferRead:
    """A currently-assigned clinician requests to share this patient with another clinician.

    Nothing changes access until the patient enters the emailed OTP (see
    consent_transfer below) -- this call only creates the request and sends
    the code.
    """
    await load_accessible_patient(patient_id, current_user, db)

    to_clinician = await db.scalar(
        select(User).where(
            User.email == payload.to_clinician_email,
            User.role == UserRole.CLINICIAN,
            User.is_active.is_(True),
        )
    )
    if to_clinician is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinician not found")
    if to_clinician.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Cannot transfer a patient to yourself"
        )
    if await is_assigned(patient_id, to_clinician.id, db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That clinician already has access to this patient"
        )

    existing_pending = await db.scalar(
        select(PatientTransfer.id).where(
            PatientTransfer.patient_id == patient_id,
            PatientTransfer.status == TransferStatus.PENDING_PATIENT_CONSENT,
        )
    )
    if existing_pending is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A transfer is already pending for this patient"
        )

    profile = await db.get(PatientProfile, patient_id)
    patient_user = await db.get(User, profile.user_id)

    otp, otp_hash, expires_at = transfer_otp.new_otp_fields()
    transfer = PatientTransfer(
        patient_id=patient_id,
        from_clinician_id=current_user.id,
        to_clinician_id=to_clinician.id,
        otp_hash=otp_hash,
        otp_expires_at=expires_at,
        attempts_remaining=settings.TRANSFER_OTP_MAX_ATTEMPTS,
    )
    db.add(transfer)
    await db.flush()
    db.add(_audit(current_user, patient_id, AuditActionType.CREATE, request))
    await db.commit()
    await db.refresh(transfer)

    # A dead mail server must not roll back a transfer that's already been
    # created and committed -- the patient/clinician can always resend-otp.
    await transfer_otp.send_otp_email(
        patient_user.email, otp, current_user.email, to_clinician.email, patient_user.id, db
    )

    return await _build_read(transfer, db)


@router.get("/transfers", response_model=list[TransferRead])
async def list_my_transfers(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TransferRead]:
    """Lists transfers involving the caller -- both sides for a clinician, own record for a patient."""
    if current_user.role == UserRole.CLINICIAN:
        stmt = select(PatientTransfer).where(
            or_(
                PatientTransfer.from_clinician_id == current_user.id,
                PatientTransfer.to_clinician_id == current_user.id,
            )
        )
    else:
        profile = await db.scalar(select(PatientProfile).where(PatientProfile.user_id == current_user.id))
        if profile is None:
            return []
        stmt = select(PatientTransfer).where(PatientTransfer.patient_id == profile.id)

    stmt = stmt.order_by(PatientTransfer.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.scalars(stmt)).all()
    return [await _build_read(t, db) for t in rows]


@router.get("/transfers/{transfer_id}", response_model=TransferRead)
async def get_transfer(
    transfer_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TransferRead:
    transfer = await _load_transfer_or_404(transfer_id, db)
    await _require_participant(transfer, current_user, db)
    return await _build_read(transfer, db)


@router.post("/transfers/{transfer_id}/consent", response_model=TransferRead)
async def consent_transfer(
    transfer_id: UUID,
    payload: TransferConsent,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.PATIENT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TransferRead:
    transfer = await _load_transfer_or_404(transfer_id, db)
    await _require_patient(transfer, current_user, db)

    if transfer.status != TransferStatus.PENDING_PATIENT_CONSENT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transfer is {transfer.status.value.lower()}, not awaiting consent",
        )

    now = dt.datetime.now(dt.timezone.utc)
    if transfer.otp_expires_at <= now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Code expired -- request a new one")

    if not transfer_otp.verify_otp(transfer, payload.otp):
        transfer.attempts_remaining -= 1
        if transfer.attempts_remaining <= 0:
            transfer.status = TransferStatus.LOCKED
            db.add(_audit(current_user, transfer.patient_id, AuditActionType.UPDATE, request))
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Too many incorrect attempts -- this request is locked",
            )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Incorrect code", "attempts_remaining": transfer.attempts_remaining},
        )

    transfer.status = TransferStatus.APPROVED
    transfer.consented_at = now
    # Adds a second, simultaneous active assignment -- never ends the
    # initiating clinician's, per the agreed design.
    await assign_clinician(transfer.patient_id, transfer.to_clinician_id, db, is_primary=False)
    db.add(_audit(current_user, transfer.patient_id, AuditActionType.UPDATE, request))
    await db.commit()
    await db.refresh(transfer)
    return await _build_read(transfer, db)


@router.post("/transfers/{transfer_id}/decline", response_model=TransferRead)
async def decline_transfer(
    transfer_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.PATIENT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TransferRead:
    transfer = await _load_transfer_or_404(transfer_id, db)
    await _require_patient(transfer, current_user, db)

    if transfer.status not in _OPEN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Transfer is already {transfer.status.value.lower()}"
        )

    transfer.status = TransferStatus.DECLINED
    db.add(_audit(current_user, transfer.patient_id, AuditActionType.UPDATE, request))
    await db.commit()
    await db.refresh(transfer)
    return await _build_read(transfer, db)


@router.post("/transfers/{transfer_id}/cancel", response_model=TransferRead)
async def cancel_transfer(
    transfer_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.CLINICIAN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TransferRead:
    transfer = await _load_transfer_or_404(transfer_id, db)

    if current_user.id not in (transfer.from_clinician_id, transfer.to_clinician_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    if current_user.id != transfer.from_clinician_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the initiating clinician can cancel this transfer"
        )

    if transfer.status not in _OPEN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Transfer is already {transfer.status.value.lower()}"
        )

    transfer.status = TransferStatus.CANCELLED
    db.add(_audit(current_user, transfer.patient_id, AuditActionType.UPDATE, request))
    await db.commit()
    await db.refresh(transfer)
    return await _build_read(transfer, db)


@router.post("/transfers/{transfer_id}/resend-otp", response_model=TransferRead)
@limiter.limit(settings.RATE_LIMIT_OTP_RESEND)
async def resend_transfer_otp(
    transfer_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(require_role(UserRole.PATIENT))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TransferRead:
    transfer = await _load_transfer_or_404(transfer_id, db)
    await _require_patient(transfer, current_user, db)

    if transfer.status not in _OPEN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Transfer is already {transfer.status.value.lower()}"
        )

    otp, otp_hash, expires_at = transfer_otp.new_otp_fields()
    transfer.otp_hash = otp_hash
    transfer.otp_expires_at = expires_at
    transfer.attempts_remaining = settings.TRANSFER_OTP_MAX_ATTEMPTS
    # A resend un-sticks a LOCKED request with a fresh code/attempt budget --
    # the lock is about one code's attempts being exhausted, not a permanent
    # decision the way decline/cancel are.
    transfer.status = TransferStatus.PENDING_PATIENT_CONSENT
    db.add(_audit(current_user, transfer.patient_id, AuditActionType.UPDATE, request))
    await db.commit()
    await db.refresh(transfer)

    from_clinician = await db.get(User, transfer.from_clinician_id)
    to_clinician = await db.get(User, transfer.to_clinician_id)
    await transfer_otp.send_otp_email(
        current_user.email, otp, from_clinician.email, to_clinician.email, current_user.id, db
    )

    return await _build_read(transfer, db)
