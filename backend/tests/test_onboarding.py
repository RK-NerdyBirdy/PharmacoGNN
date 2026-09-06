from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from tests.conftest import PROFILE_FIELDS, TEST_PASSWORD, invite_token_for, onboard_patient, unique_email


@pytest.fixture(autouse=True)
def _clear_outbox():
    from app.services.email import get_backend

    get_backend().clear()
    yield


def _onboard(client, clinician_headers, email=None):
    body = {**PROFILE_FIELDS, "email": email or unique_email("invitee")}
    r = client.post("/api/v1/patients", headers=clinician_headers, json=body)
    assert r.status_code == 201, r.text
    return body["email"], r.json()


# --- Invite issuance ---------------------------------------------------------


def test_onboarding_sends_invite_and_creates_pending_account(client, clinician_headers):
    from app.services.email import get_backend

    email, profile = _onboard(client, clinician_headers)

    assert profile["activation_status"] == "pending"
    assert profile["invite_email_status"] == "sent"

    message = get_backend().last_to(email)
    assert message is not None
    assert "activate?token=" in message.body
    # The invite must never carry a password or any clinical detail.
    assert TEST_PASSWORD not in message.body
    assert PROFILE_FIELDS["medical_record_number"] not in message.body


def test_account_is_unusable_before_activation(client, clinician_headers):
    email, _ = _onboard(client, clinician_headers)

    r = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert r.status_code == 401  # generic -- can't be used to detect pending invites


def test_roster_shows_pending_until_activated(client, clinician_headers):
    email, profile = _onboard(client, clinician_headers)

    r = client.get("/api/v1/patients", headers=clinician_headers)
    row = next(p for p in r.json() if p["id"] == profile["id"])
    assert row["activation_status"] == "pending"

    token = invite_token_for(email)
    client.post("/api/v1/auth/activate", json={"token": token, "password": TEST_PASSWORD})

    r = client.get("/api/v1/patients", headers=clinician_headers)
    row = next(p for p in r.json() if p["id"] == profile["id"])
    assert row["activation_status"] == "active"


# --- Activation --------------------------------------------------------------


def test_preview_then_activate(client, clinician_headers):
    email, _ = _onboard(client, clinician_headers)
    token = invite_token_for(email)

    r = client.get(f"/api/v1/auth/activate/{token}")
    assert r.status_code == 200
    assert r.json()["email"] == email

    r = client.post("/api/v1/auth/activate", json={"token": token, "password": TEST_PASSWORD})
    assert r.status_code == 200
    assert r.json()["access_token"]

    # ...and the account now works normally.
    r = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert r.status_code == 200


def test_activation_token_is_single_use(client, clinician_headers):
    email, _ = _onboard(client, clinician_headers)
    token = invite_token_for(email)

    assert client.post(
        "/api/v1/auth/activate", json={"token": token, "password": TEST_PASSWORD}
    ).status_code == 200

    r = client.post("/api/v1/auth/activate", json={"token": token, "password": "different-pw-1"})
    assert r.status_code == 409

    r = client.get(f"/api/v1/auth/activate/{token}")
    assert r.status_code == 409


def test_unknown_token_404s(client):
    assert client.get("/api/v1/auth/activate/not-a-real-token").status_code == 404
    r = client.post("/api/v1/auth/activate", json={"token": "nope", "password": TEST_PASSWORD})
    assert r.status_code == 404


def test_expired_token_is_gone(client, clinician_headers):
    """Expire the invite directly, then confirm both endpoints report 410."""
    import app.main  # noqa: F401  (ensures app modules are loaded)
    from app.db.session import AsyncSessionLocal
    from app.models.invitation import UserInvitation
    from app.services.invitations import _hash

    email, _ = _onboard(client, clinician_headers)
    token = invite_token_for(email)

    async def _expire():
        async with AsyncSessionLocal() as db:
            invitation = await db.scalar(
                select(UserInvitation).where(UserInvitation.token_hash == _hash(token))
            )
            invitation.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
            await db.commit()

    client.portal.call(_expire)  # run on the TestClient's event loop

    assert client.get(f"/api/v1/auth/activate/{token}").status_code == 410
    r = client.post("/api/v1/auth/activate", json={"token": token, "password": TEST_PASSWORD})
    assert r.status_code == 410


def test_short_password_rejected_at_activation(client, clinician_headers):
    email, _ = _onboard(client, clinician_headers)
    token = invite_token_for(email)

    r = client.post("/api/v1/auth/activate", json={"token": token, "password": "short"})
    assert r.status_code == 422


# --- Resend ------------------------------------------------------------------


def test_resend_invalidates_the_previous_link(client, clinician_headers):
    email, profile = _onboard(client, clinician_headers)
    first_token = invite_token_for(email)

    r = client.post(
        f"/api/v1/patients/{profile['id']}/invite/resend", headers=clinician_headers
    )
    assert r.status_code == 200
    assert r.json()["invite_email_status"] == "sent"

    second_token = invite_token_for(email)
    assert second_token != first_token

    # The superseded link must not still work.
    assert client.get(f"/api/v1/auth/activate/{first_token}").status_code == 410
    assert client.get(f"/api/v1/auth/activate/{second_token}").status_code == 200


def test_resend_rejected_once_activated(client, clinician_headers):
    patient = onboard_patient(client, clinician_headers)
    r = client.post(
        f"/api/v1/patients/{patient['patient_id']}/invite/resend", headers=clinician_headers
    )
    assert r.status_code == 409


def test_unassigned_clinician_cannot_resend(client, clinician_headers, other_clinician_headers):
    _, profile = _onboard(client, clinician_headers)
    r = client.post(
        f"/api/v1/patients/{profile['id']}/invite/resend", headers=other_clinician_headers
    )
    assert r.status_code == 404


# --- Mail failure must not block onboarding ----------------------------------


def test_patient_is_still_created_when_email_fails(client, clinician_headers, monkeypatch):
    """A dead mail server is a warning, not a failed clinical operation."""
    from app.services import email as email_service

    async def _boom(message):
        raise ConnectionRefusedError("SMTP down")

    monkeypatch.setattr(email_service.get_backend(), "send", _boom)

    email, profile = _onboard(client, clinician_headers)
    assert profile["invite_email_status"] == "failed"

    # The record exists and is usable by the clinician despite the mail failure.
    r = client.get(f"/api/v1/patients/{profile['id']}", headers=clinician_headers)
    assert r.status_code == 200


# --- Self-registration is closed to patients ---------------------------------


def test_patient_self_registration_is_rejected(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": unique_email("selfreg"), "password": TEST_PASSWORD, "role": "PATIENT"},
    )
    assert r.status_code == 403


def test_clinician_self_registration_still_works(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": unique_email("doc"), "password": TEST_PASSWORD, "role": "CLINICIAN"},
    )
    assert r.status_code == 201
