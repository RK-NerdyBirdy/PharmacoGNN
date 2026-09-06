"""Issuing, verifying, and emailing patient-transfer consent OTPs.

Mirrors services/invitations.py's shape (generate a secret, store only its
hash, email the plaintext once, verify by re-hashing) -- same reasoning,
a different secret: a 6-digit code a person types, not a URL token.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import secrets
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.email import EmailDelivery, EmailStatus
from app.models.transfer import PatientTransfer
from app.services import email as email_service

logger = logging.getLogger(__name__)


def _hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode("utf-8")).hexdigest()


def _generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def new_otp_fields() -> tuple[str, str, dt.datetime]:
    """Returns (plaintext_otp, otp_hash, expires_at) for a fresh code.

    The plaintext is returned once, for the caller to email immediately, and
    is never stored anywhere -- only the hash persists on the row.
    """
    otp = _generate_otp()
    expires_at = _now() + dt.timedelta(minutes=settings.TRANSFER_OTP_TTL_MINUTES)
    return otp, _hash_otp(otp), expires_at


def verify_otp(transfer: PatientTransfer, otp: str) -> bool:
    return secrets.compare_digest(transfer.otp_hash, _hash_otp(otp))


async def send_otp_email(
    to_email: str,
    otp: str,
    from_clinician_email: str,
    to_clinician_email: str,
    patient_user_id: UUID,
    db: AsyncSession,
) -> str:
    """Send the consent OTP and record the outcome. Never raises.

    Same reasoning as invitations.send_invite_email: a dead mail server must
    not roll back a transfer request that's already been created and
    committed -- the initiating clinician gets a normal response either way,
    and the patient (or clinician, via resend) can retry delivery.
    """
    message = email_service.build_transfer_otp_email(to_email, otp, from_clinician_email, to_clinician_email)
    delivery_status = EmailStatus.SENT
    error: str | None = None

    try:
        await email_service.send_message(message)
    except Exception as exc:  # noqa: BLE001 - any transport failure is non-fatal here
        delivery_status = EmailStatus.FAILED
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("Transfer OTP email to %s failed: %s", to_email, error)

    db.add(
        EmailDelivery(
            to_email=to_email,
            subject=message.subject,
            template=message.template,
            status=delivery_status,
            error=error,
            related_user_id=patient_user_id,
        )
    )
    await db.commit()

    return "sent" if delivery_status is EmailStatus.SENT else "failed"
