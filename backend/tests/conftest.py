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
# Capture mail in-process instead of talking to MailHog/SMTP, so the suite is
# hermetic and can read invite tokens straight out of the outbox.
os.environ.setdefault("EMAIL_BACKEND", "memory")

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
def other_clinician_headers(client: TestClient) -> dict[str, str]:
    """A second clinician with no assignment to anyone -- for access-scoping tests."""
    headers, _ = _register_and_login(client, "CLINICIAN", "clinician_other")
    return headers


PROFILE_FIELDS = {
    "legal_name": "Jane Doe",
    "date_of_birth": "1990-05-14",
    "medical_record_number": "MRN-TEST-0001",
    "emergency_contact": "John Doe, 555-1234",
    "biological_sex": "FEMALE",
    "age": 36,
}


def invite_token_for(email: str) -> str:
    """Pull the activation token out of the captured invite email."""
    from app.services.email import get_backend

    message = get_backend().last_to(email)
    assert message is not None, f"no invite email captured for {email}"
    return message.body.split("token=")[1].split()[0]


def onboard_patient(
    client: TestClient, clinician_headers: dict[str, str], *, activate: bool = True, **overrides
) -> dict:
    """Create a patient the way a clinician actually does, then activate them.

    Patients can't self-register any more, so every patient in the suite comes
    through this -- which means the tests exercise the real onboarding path
    rather than a shortcut that no longer exists in production.
    """
    email = unique_email("patient")
    body = {**PROFILE_FIELDS, **overrides, "email": email}

    r = client.post("/api/v1/patients", headers=clinician_headers, json=body)
    assert r.status_code == 201, r.text
    profile = r.json()

    result = {
        "patient_id": profile["id"],
        "user_id": profile["user_id"],
        "email": email,
        "profile": profile,
        "headers": None,
    }
    if activate:
        token = invite_token_for(email)
        r = client.post("/api/v1/auth/activate", json={"token": token, "password": TEST_PASSWORD})
        assert r.status_code == 200, r.text
        result["headers"] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return result


@pytest.fixture
def patient(client: TestClient, clinician_headers: dict[str, str]) -> dict:
    """An onboarded, activated patient assigned to `clinician_headers`."""
    return onboard_patient(client, clinician_headers)


@pytest.fixture
def other_patient(client: TestClient, clinician_headers: dict[str, str]) -> dict:
    """A second distinct patient -- for cross-patient access tests."""
    return onboard_patient(client, clinician_headers)
