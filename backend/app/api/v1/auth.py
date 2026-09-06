from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole
from app.schemas.auth import (
    ActivateAccount,
    InvitationPreview,
    Token,
    UserLogin,
    UserRead,
    UserRegister,
)
from app.services import invitations

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register(
    request: Request, payload: UserRegister, db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """Clinician self-signup.

    Patients cannot register here: their account is created by a clinician
    (POST /patients), which also creates their profile, the assignment that
    grants access, and the invite that lets them set a password. A patient
    self-registering would produce an account with no profile and no
    clinician, which can see nothing and serves no purpose -- and it would be
    a way to create patient logins outside the onboarding flow.
    """
    if payload.role is not UserRole.CLINICIAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient accounts are created by a clinician, not self-registered",
        )

    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=payload.email, hashed_password=hash_password(payload.password), role=payload.role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    request: Request, payload: UserLogin, db: Annotated[AsyncSession, Depends(get_db)]
) -> Token:
    user = await db.scalar(select(User).where(User.email == payload.email))

    # An un-activated account (hashed_password IS NULL) fails here with the
    # same generic message as a wrong password -- deliberately, so login can't
    # be used to enumerate which addresses have pending invites.
    if (
        user is None
        or user.hashed_password is None
        or not verify_password(payload.password, user.hashed_password)
        or not user.is_active
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    access_token = create_access_token(subject=str(user.id), role=user.role.value)
    return Token(access_token=access_token)


@router.get("/activate/{token}", response_model=InvitationPreview)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def preview_invitation(
    request: Request, token: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> InvitationPreview:
    """Validate an invite before showing the set-password form.

    Distinct statuses here (410 expired / 409 used / 404 unknown) so the
    activation page can say something useful. That's a deliberate trade: it
    leaks whether a *token* is real, but tokens are 256-bit random values, so
    guessing one isn't a practical attack, and a patient staring at "invalid
    link" with no idea why is a real support cost.
    """
    invitation = await invitations.find_invitation(token, db)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invitation")
    if invitation.used_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invitation already used")
    if not invitation.is_redeemable(dt.datetime.now(dt.timezone.utc)):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invitation expired")

    user = await db.get(User, invitation.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invitation")

    return InvitationPreview(email=user.email, expires_at=invitation.expires_at)


@router.post("/activate", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def activate_account(
    request: Request, payload: ActivateAccount, db: Annotated[AsyncSession, Depends(get_db)]
) -> Token:
    """Redeem an invite: set the first password and log straight in."""
    invitation = await invitations.find_invitation(payload.token, db)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invitation")
    if invitation.used_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invitation already used")
    if not invitation.is_redeemable(dt.datetime.now(dt.timezone.utc)):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invitation expired")

    user = await db.get(User, invitation.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invitation")

    user.hashed_password = hash_password(payload.password)
    await invitations.redeem_invitation(invitation, db)
    await db.commit()

    access_token = create_access_token(subject=str(user.id), role=user.role.value)
    return Token(access_token=access_token)


@router.post("/refresh", response_model=Token)
async def refresh(current_user: Annotated[User, Depends(get_current_user)]) -> Token:
    """Re-issues a fresh access token from a still-valid one.

    This is the simple "sliding session" pattern -- it re-signs a new token
    as long as the current one hasn't expired yet (get_current_user already
    rejects expired/invalid tokens with 401), not a separate long-lived
    refresh-token type with its own revocation/rotation. A client should call
    this proactively before ACCESS_TOKEN_EXPIRE_MINUTES elapses; once a token
    has actually expired there is nothing to refresh from and the user must
    log in again.
    """
    access_token = create_access_token(subject=str(current_user.id), role=current_user.role.value)
    return Token(access_token=access_token)
