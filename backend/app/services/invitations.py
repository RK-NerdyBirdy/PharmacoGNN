"""Issuing and redeeming patient invite tokens."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import secrets
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.email import EmailDelivery, EmailStatus
from app.models.invitation import UserInvitation
from app.services import email as email_service

logger = logging.getLogger(__name__)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


async def issue_invitation(
    user_id: UUID, db: AsyncSession, *, created_by: UUID | None = None
) -> str:
    """Create an invite and return the plaintext token (the only time it exists).

    Any earlier unused invite for this user is expired first, so a resend
    genuinely invalidates the previous link rather than leaving two live ones.
    Caller commits.
    """
    await db.execute(
        update(UserInvitation)
        .where(UserInvitation.user_id == user_id, UserInvitation.used_at.is_(None))
        .values(expires_at=_now())
    )

    token = secrets.token_urlsafe(32)
    db.add(
        UserInvitation(
            user_id=user_id,
            token_hash=_hash(token),
            expires_at=_now() + dt.timedelta(hours=settings.INVITE_TOKEN_TTL_HOURS),
            created_by=created_by,
        )
    )
    await db.flush()
    return token


async def find_invitation(token: str, db: AsyncSession) -> UserInvitation | None:
    return await db.scalar(select(UserInvitation).where(UserInvitation.token_hash == _hash(token)))


async def redeem_invitation(invitation: UserInvitation, db: AsyncSession) -> None:
    """Mark an invite consumed. Caller commits."""
    invitation.used_at = _now()
    await db.flush()


async def send_invite_email(to_email: str, token: str, user_id: UUID, db: AsyncSession) -> str:
    """Send the invite and record the outcome. Never raises.

    Returns "sent" or "failed". A dead mail server must not roll back a
    patient that was already created and committed -- the clinician gets a
    warning and a resend button instead of a failed operation.
    """
    message = email_service.build_invite_email(to_email, token)
    status = EmailStatus.SENT
    error: str | None = None

    try:
        await email_service.send_message(message)
    except Exception as exc:  # noqa: BLE001 - any transport failure is non-fatal here
        status = EmailStatus.FAILED
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("Invite email to %s failed: %s", to_email, error)

    db.add(
        EmailDelivery(
            to_email=to_email,
            subject=message.subject,
            template=message.template,
            status=status,
            error=error,
            related_user_id=user_id,
        )
    )
    await db.commit()

    return "sent" if status is EmailStatus.SENT else "failed"
