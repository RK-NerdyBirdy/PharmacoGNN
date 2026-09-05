from __future__ import annotations

import ipaddress

from fastapi import Request


def client_ip(request: Request) -> str | None:
    """Validated client IP for AuditLog.ip_address (a strict Postgres INET column).

    request.client.host is not guaranteed to be a real IP -- Starlette's own
    TestClient sends the literal string "testclient", and some proxy/test
    setups can produce other non-IP values. Passing that straight to an INET
    column raises a raw asyncpg DataError and 500s an otherwise-valid
    request; validate and fall back to None (the column is nullable) instead.
    """
    if request.client is None:
        return None
    try:
        ipaddress.ip_address(request.client.host)
    except ValueError:
        return None
    return request.client.host
