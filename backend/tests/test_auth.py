from __future__ import annotations

from tests.conftest import TEST_PASSWORD, unique_email


def test_register_and_login(client):
    email = unique_email("authflow")

    r = client.post(
        "/api/v1/auth/register", json={"email": email, "password": TEST_PASSWORD, "role": "CLINICIAN"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == email
    assert body["role"] == "CLINICIAN"
    assert body["is_active"] is True
    assert "hashed_password" not in body  # never leak the hash

    r = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_register_duplicate_email_conflicts(client):
    payload = {"email": unique_email("dup"), "password": TEST_PASSWORD, "role": "CLINICIAN"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 409


def test_login_wrong_password(client):
    email = unique_email("wrongpw")
    client.post("/api/v1/auth/register", json={"email": email, "password": TEST_PASSWORD, "role": "PATIENT"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "not-the-password"})
    assert r.status_code == 401


def test_login_unknown_email(client):
    r = client.post("/api/v1/auth/login", json={"email": unique_email("ghost"), "password": "whatever1"})
    assert r.status_code == 401


def test_register_rejects_short_password(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": unique_email("shortpw"), "password": "short", "role": "PATIENT"},
    )
    assert r.status_code == 422


def test_refresh_with_valid_token(client, clinician_headers):
    r = client.post("/api/v1/auth/refresh", headers=clinician_headers)
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_refresh_rejects_missing_token(client):
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


def test_protected_endpoint_rejects_missing_token(client):
    r = client.post(
        "/api/v1/predict/pairwise", json={"drug_a_cid": "CID000000085", "drug_b_cid": "CID000000119"}
    )
    assert r.status_code == 401


def test_protected_endpoint_rejects_garbage_token(client):
    r = client.get("/api/v1/vocab/drugs", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert r.status_code == 401
