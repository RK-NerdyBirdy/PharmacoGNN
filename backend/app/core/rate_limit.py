from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# A neutral module (not main.py) so routers can import `limiter` for
# @limiter.limit(...) decorators without a circular import back to main.py,
# which is what assembles the routers in the first place.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    enabled=settings.RATE_LIMIT_ENABLED,
)
