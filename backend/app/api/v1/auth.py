from typing import Annotated, Any

# 1. Import OAuth2PasswordRequestForm
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import Token, UserRead, UserRegister

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register(
    request: Request, payload: UserRegister, db: Annotated[AsyncSession, Depends(get_db)]
) -> Any:
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
    request: Request, 
    # 2. Swap UserLogin payload for OAuth2 Form Data
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()], 
    db: Annotated[AsyncSession, Depends(get_db)]
) -> Any:
    # 3. form_data uses the key 'username', so we map that to our email column
    user = await db.scalar(select(User).where(User.email == form_data.username))
    if user is None or not verify_password(form_data.password, user.hashed_password) or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    access_token = create_access_token(subject=str(user.id), role=user.role.value)
    
    # 4. Standard OAuth2 expects the token_type to be included
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh", response_model=Token)
async def refresh(current_user: Annotated[User, Depends(get_current_user)]) -> Any:
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