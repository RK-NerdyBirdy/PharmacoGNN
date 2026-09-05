from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.models.user import User, UserRole

# OAuth2PasswordBearer used to sit here, but its Swagger "Authorize" dialog
# submits a username/password form directly to tokenUrl -- which doesn't
# match /auth/login's actual contract (a JSON {email, password} body), so
# the built-in flow never worked. HTTPBearer instead renders a single
# "paste your token" field in Swagger, which is what /auth/login actually
# produces: call it separately (its own "Try it out" in /docs, or curl),
# copy the access_token, and paste just that (no "Bearer " prefix) here.
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Paste the access_token from POST /auth/login (just the raw token, not prefixed with 'Bearer ').",
)

# Re-exported so routers only ever import from app.api.deps, never db.session directly.
get_db = get_db_session


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    # auto_error=False on HTTPBearer above means a missing header lands here
    # as None rather than HTTPBearer's own default of 403 -- kept as a
    # uniform 401 either way, matching what's documented/tested.
    if credentials is None:
        raise credentials_error

    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise credentials_error from exc

    raw_subject = payload.get("sub")
    if raw_subject is None:
        raise credentials_error

    try:
        user_id = UUID(raw_subject)
    except ValueError as exc:
        raise credentials_error from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return user


def require_role(*roles: UserRole):
    """Dependency factory: `Depends(require_role(UserRole.CLINICIAN))`."""

    async def _guard(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(r.value for r in roles)}",
            )
        return current_user

    return _guard
