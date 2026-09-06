from __future__ import annotations


def _profile_payload(**overrides):
    payload = {
        "legal_name": "Jane Doe",
        "date_of_birth": "1990-05-14",
        "medical_record_number": "MRN-TEST-0001",
        "emergency_contact": "John Doe, 555-1234",
        "biological_sex": "FEMALE",
        "age": 36,
    }
    payload.update(overrides)
    return payload


def _create_profile(client, clinician_headers, patient_user_id):
    r = client.post(
        "/api/v1/patients",
        headers=clinician_headers,
        json={**_profile_payload(), "user_id": patient_user_id},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_clinician_creates_and_reads_patient_profile(client, clinician_headers, patient_user):
    patient_headers, patient_user_id = patient_user

    profile = _create_profile(client, clinician_headers, patient_user_id)
    assert profile["user_id"] == patient_user_id
    assert profile["legal_name"] == "Jane Doe"
    assert profile["biological_sex"] == "FEMALE"
    patient_id = profile["id"]

    # Encrypted PHI round-trips correctly through the API (encryption is
    # transparent at the DB layer -- this is really testing that, not just
    # the HTTP contract).
    r = client.get(f"/api/v1/patients/{patient_id}", headers=clinician_headers)
    assert r.status_code == 200
    assert r.json()["medical_record_number"] == "MRN-TEST-0001"

    r = client.get(f"/api/v1/patients/{patient_id}", headers=patient_headers)
    assert r.status_code == 200

    r = client.get("/api/v1/patients/me", headers=patient_headers)
    assert r.status_code == 200
    assert r.json()["id"] == patient_id


def test_duplicate_profile_conflicts(client, clinician_headers, patient_user):
    _, patient_user_id = patient_user
    _create_profile(client, clinician_headers, patient_user_id)

    r = client.post(
        "/api/v1/patients",
        headers=clinician_headers,
        json={**_profile_payload(), "user_id": patient_user_id},
    )
    assert r.status_code == 409


def test_self_service_profile_flow(client, patient_user):
    patient_headers, _ = patient_user

    r = client.get("/api/v1/patients/me", headers=patient_headers)
    assert r.status_code == 404

    r = client.post("/api/v1/patients/me", headers=patient_headers, json=_profile_payload())
    assert r.status_code == 201

    r = client.post("/api/v1/patients/me", headers=patient_headers, json=_profile_payload())
    assert r.status_code == 409


def test_patient_cannot_read_other_patients_profile(client, clinician_headers, patient_user, patient_user_2):
    _, patient_user_id = patient_user
    other_headers, _ = patient_user_2

    profile = _create_profile(client, clinician_headers, patient_user_id)

    r = client.get(f"/api/v1/patients/{profile['id']}", headers=other_headers)
    assert r.status_code == 403


def test_patient_cannot_create_profile_for_another_user(client, patient_user, patient_user_2):
    _, patient_user_id = patient_user
    other_headers, _ = patient_user_2

    r = client.post(
        "/api/v1/patients",
        headers=other_headers,
        json={**_profile_payload(), "user_id": patient_user_id},
    )
    assert r.status_code == 403  # require_role(CLINICIAN) rejects a PATIENT caller


def test_update_profile(client, clinician_headers, patient_user):
    _, patient_user_id = patient_user
    profile = _create_profile(client, clinician_headers, patient_user_id)

    r = client.patch(f"/api/v1/patients/{profile['id']}", headers=clinician_headers, json={"age": 37})
    assert r.status_code == 200
    assert r.json()["age"] == 37
    assert r.json()["legal_name"] == "Jane Doe"  # untouched fields survive a partial update


def test_patient_cannot_add_own_condition_or_regimen(client, clinician_headers, patient_user):
    patient_headers, patient_user_id = patient_user
    profile = _create_profile(client, clinician_headers, patient_user_id)
    patient_id = profile["id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/conditions",
        headers=patient_headers,
        json={"condition_name": "Self-diagnosed"},
    )
    assert r.status_code == 403

    r = client.post(
        f"/api/v1/patients/{patient_id}/regimens",
        headers=patient_headers,
        json={"pubchem_cid": 85, "drug_name": "Self-prescribed", "start_date": "2024-01-01"},
    )
    assert r.status_code == 403


def test_condition_lifecycle(client, clinician_headers, patient_user):
    patient_headers, patient_user_id = patient_user
    patient_id = _create_profile(client, clinician_headers, patient_user_id)["id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/conditions",
        headers=clinician_headers,
        json={"condition_name": "Hypertension", "icd10_code": "I10", "diagnosed_date": "2020-01-01"},
    )
    assert r.status_code == 201
    condition = r.json()
    assert condition["is_active"] is True
    condition_id = condition["id"]

    r = client.get(f"/api/v1/patients/{patient_id}/conditions", headers=patient_headers)
    assert r.status_code == 200
    assert any(c["id"] == condition_id for c in r.json())

    r = client.get(
        f"/api/v1/patients/{patient_id}/conditions", params={"active_only": True}, headers=clinician_headers
    )
    assert any(c["id"] == condition_id for c in r.json())

    r = client.patch(
        f"/api/v1/patients/{patient_id}/conditions/{condition_id}",
        headers=clinician_headers,
        json={"is_active": False},
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    r = client.get(
        f"/api/v1/patients/{patient_id}/conditions", params={"active_only": True}, headers=clinician_headers
    )
    assert all(c["id"] != condition_id for c in r.json())


def test_regimen_lifecycle(client, clinician_headers, patient_user):
    _, patient_user_id = patient_user
    patient_id = _create_profile(client, clinician_headers, patient_user_id)["id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/regimens",
        headers=clinician_headers,
        json={"pubchem_cid": 85, "drug_name": "Test Drug", "dosage": "10mg BID", "start_date": "2024-01-01"},
    )
    assert r.status_code == 201
    regimen = r.json()
    assert regimen["end_date"] is None
    assert regimen["prescriber_id"] is not None
    regimen_id = regimen["id"]

    r = client.get(
        f"/api/v1/patients/{patient_id}/regimens", params={"active_only": True}, headers=clinician_headers
    )
    assert any(reg["id"] == regimen_id for reg in r.json())

    r = client.patch(
        f"/api/v1/patients/{patient_id}/regimens/{regimen_id}",
        headers=clinician_headers,
        json={"end_date": "2024-06-01"},
    )
    assert r.status_code == 200
    assert r.json()["end_date"] == "2024-06-01"

    r = client.get(
        f"/api/v1/patients/{patient_id}/regimens", params={"active_only": True}, headers=clinician_headers
    )
    assert all(reg["id"] != regimen_id for reg in r.json())


def test_unknown_patient_id_404s(client, clinician_headers):
    r = client.get("/api/v1/patients/00000000-0000-0000-0000-000000000000", headers=clinician_headers)
    assert r.status_code == 404
