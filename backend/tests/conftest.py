from __future__ import annotations

import os
import uuid
from pathlib import Path

# Must happen before the first `import app...` anywhere (including
# transitively, via the migration step below) -- app.core.config.settings is
# an lru_cache'd singleton, so whichever import happens first freezes the
# value for the whole test session. Disabled so rapid test requests don't
# trip the same per-IP bucket the real app protects login/register with.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_PASSWORD = "supersecret1"


def unique_email(prefix: str = "test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}@example.com"


def _run_migrations() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> None:
    """Idempotent: safe to run against an already-migrated dev DB."""
    _run_migrations()


@pytest.fixture(scope="session")
def client():
    """Session-scoped so gnn_engine.initialize() (fast now, thanks to
    z_drug_cache.pt) runs once for the whole test run, not once per test."""
    import app.main as main_module

    with TestClient(main_module.app) as test_client:
        yield test_client


def _register_and_login(client: TestClient, role: str, prefix: str) -> tuple[dict[str, str], str]:
    email = unique_email(prefix)
    r = client.post(
        "/api/v1/auth/register", json={"email": email, "password": TEST_PASSWORD, "role": role}
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    r = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}, user_id


@pytest.fixture
def clinician_headers(client: TestClient) -> dict[str, str]:
    headers, _ = _register_and_login(client, "CLINICIAN", "clinician")
    return headers


@pytest.fixture
def patient_user(client: TestClient) -> tuple[dict[str, str], str]:
    """(auth_headers, user_id) for a fresh PATIENT-role user with no profile yet."""
    return _register_and_login(client, "PATIENT", "patient")


@pytest.fixture
def patient_user_2(client: TestClient) -> tuple[dict[str, str], str]:
    """A second, distinct patient -- for cross-patient RBAC tests."""
    return _register_and_login(client, "PATIENT", "patient2")
