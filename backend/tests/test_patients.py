from __future__ import annotations

from tests.conftest import onboard_patient


# --- Creation + assignment ---------------------------------------------------


def test_clinician_onboards_and_reads_patient(client, clinician_headers, patient):
    patient_id = patient["patient_id"]
    assert patient["profile"]["legal_name"] == "Jane Doe"

    # Encrypted PHI round-trips through the API (really testing the DB-layer
    # encryption, not just the HTTP contract).
    r = client.get(f"/api/v1/patients/{patient_id}", headers=clinician_headers)
    assert r.status_code == 200
    assert r.json()["medical_record_number"] == "MRN-TEST-0001"

    r = client.get("/api/v1/patients/me", headers=patient["headers"])
    assert r.status_code == 200
    assert r.json()["id"] == patient_id


def test_creating_clinician_is_assigned_as_primary(client, clinician_headers, patient):
    r = client.get(f"/api/v1/patients/{patient['patient_id']}/access", headers=clinician_headers)
    assert r.status_code == 200
    access = r.json()
    assert len(access) == 1
    assert access[0]["is_primary"] is True


def test_new_patient_appears_in_creating_clinicians_roster(client, clinician_headers, patient):
    r = client.get("/api/v1/patients", headers=clinician_headers)
    assert r.status_code == 200
    mine = [p for p in r.json() if p["id"] == patient["patient_id"]]
    assert len(mine) == 1
    assert mine[0]["is_primary"] is True
    assert mine[0]["active_regimen_count"] == 0
    assert mine[0]["activation_status"] == "active"


def test_duplicate_email_conflicts(client, clinician_headers, patient):
    from tests.conftest import PROFILE_FIELDS

    r = client.post(
        "/api/v1/patients",
        headers=clinician_headers,
        json={**PROFILE_FIELDS, "email": patient["email"]},
    )
    assert r.status_code == 409


# --- Assignment scoping ------------------------------------------------------


def test_unassigned_clinician_gets_404_not_403(client, other_clinician_headers, patient):
    """404, not 403 -- a 403 would confirm the patient exists."""
    patient_id = patient["patient_id"]
    for path in [
        f"/api/v1/patients/{patient_id}",
        f"/api/v1/patients/{patient_id}/conditions",
        f"/api/v1/patients/{patient_id}/regimens",
        f"/api/v1/patients/{patient_id}/access",
    ]:
        r = client.get(path, headers=other_clinician_headers)
        assert r.status_code == 404, f"{path} -> {r.status_code}"


def test_unassigned_clinician_cannot_write(client, other_clinician_headers, patient):
    patient_id = patient["patient_id"]

    r = client.patch(f"/api/v1/patients/{patient_id}", headers=other_clinician_headers, json={"age": 99})
    assert r.status_code == 404

    r = client.post(
        f"/api/v1/patients/{patient_id}/conditions",
        headers=other_clinician_headers,
        json={"condition_name": "Injected"},
    )
    assert r.status_code == 404


def test_unassigned_clinician_roster_excludes_other_patients(
    client, other_clinician_headers, patient
):
    r = client.get("/api/v1/patients", headers=other_clinician_headers)
    assert r.status_code == 200
    assert all(p["id"] != patient["patient_id"] for p in r.json())


def test_patient_cannot_read_other_patients_profile(client, patient, other_patient):
    r = client.get(f"/api/v1/patients/{patient['patient_id']}", headers=other_patient["headers"])
    assert r.status_code == 404


def test_predict_with_unassigned_patient_id_is_blocked(
    client, clinician_headers, other_clinician_headers, patient
):
    """The predict path resolves patient_id too -- it must be gated identically."""
    body = {
        "drug_a_cid": "CID000002244",
        "drug_b_cid": "CID000004201",
        "patient_id": patient["patient_id"],
    }

    r = client.post("/api/v1/predict/pairwise", headers=other_clinician_headers, json=body)
    assert r.status_code == 404

    r = client.post("/api/v1/predict/pairwise", headers=clinician_headers, json=body)
    assert r.status_code == 200


# --- Patient is read-only for clinical data ----------------------------------


def test_patient_self_service_profile_creation_is_gone(client, patient):
    """Patients never create their own profile -- a clinician onboards them."""
    r = client.post("/api/v1/patients/me", headers=patient["headers"], json={"age": 30})
    assert r.status_code in (404, 405)


def test_patient_can_edit_own_demographics(client, patient):
    r = client.patch(
        "/api/v1/patients/me",
        headers=patient["headers"],
        json={"legal_name": "Jane Q. Doe", "age": 37, "emergency_contact": "Jim, 555-9999"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["legal_name"] == "Jane Q. Doe"
    assert body["age"] == 37
    assert body["emergency_contact"] == "Jim, 555-9999"
    # Clinical identifiers untouched.
    assert body["medical_record_number"] == "MRN-TEST-0001"
    assert body["date_of_birth"] == "1990-05-14"


def test_patient_cannot_edit_clinical_fields(client, patient):
    r = client.patch(
        "/api/v1/patients/me",
        headers=patient["headers"],
        json={"biological_sex": "MALE", "medical_record_number": "MRN-HACKED"},
    )
    assert r.status_code == 422  # rejected outright, not silently dropped

    r = client.get("/api/v1/patients/me", headers=patient["headers"])
    assert r.json()["biological_sex"] == "FEMALE"
    assert r.json()["medical_record_number"] == "MRN-TEST-0001"


def test_patient_cannot_use_clinician_profile_endpoint(client, patient):
    """403 (not 404) here: the record isn't hidden from them, only the operation is."""
    r = client.patch(
        f"/api/v1/patients/{patient['patient_id']}", headers=patient["headers"], json={"age": 99}
    )
    assert r.status_code == 403


def test_patient_cannot_onboard_another_patient(client, patient):
    from tests.conftest import PROFILE_FIELDS, unique_email

    r = client.post(
        "/api/v1/patients",
        headers=patient["headers"],
        json={**PROFILE_FIELDS, "email": unique_email("sneaky")},
    )
    assert r.status_code == 403


def test_patient_cannot_add_own_condition_or_regimen(client, patient):
    patient_id = patient["patient_id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/conditions",
        headers=patient["headers"],
        json={"condition_name": "Self-diagnosed"},
    )
    assert r.status_code == 403

    r = client.post(
        f"/api/v1/patients/{patient_id}/regimens",
        headers=patient["headers"],
        json={"pubchem_cid": 85, "drug_name": "Self-prescribed", "start_date": "2024-01-01"},
    )
    assert r.status_code == 403


# --- Clinical data lifecycle (assigned clinician) ----------------------------


def test_update_profile(client, clinician_headers, patient):
    r = client.patch(
        f"/api/v1/patients/{patient['patient_id']}", headers=clinician_headers, json={"age": 37}
    )
    assert r.status_code == 200
    assert r.json()["age"] == 37
    assert r.json()["legal_name"] == "Jane Doe"


def test_condition_lifecycle(client, clinician_headers, patient):
    patient_id = patient["patient_id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/conditions",
        headers=clinician_headers,
        json={"condition_name": "Hypertension", "icd10_code": "I10", "diagnosed_date": "2020-01-01"},
    )
    assert r.status_code == 201
    condition_id = r.json()["id"]
    assert r.json()["is_active"] is True

    # Patient can read their own conditions.
    r = client.get(f"/api/v1/patients/{patient_id}/conditions", headers=patient["headers"])
    assert r.status_code == 200
    assert any(c["id"] == condition_id for c in r.json())

    r = client.patch(
        f"/api/v1/patients/{patient_id}/conditions/{condition_id}",
        headers=clinician_headers,
        json={"is_active": False},
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    r = client.get(
        f"/api/v1/patients/{patient_id}/conditions",
        params={"active_only": True},
        headers=clinician_headers,
    )
    assert all(c["id"] != condition_id for c in r.json())


def test_regimen_lifecycle(client, clinician_headers, patient):
    patient_id = patient["patient_id"]

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
        f"/api/v1/patients/{patient_id}/regimens",
        params={"active_only": True},
        headers=clinician_headers,
    )
    assert any(reg["id"] == regimen_id for reg in r.json())

    # Roster reflects the active medication count.
    r = client.get("/api/v1/patients", headers=clinician_headers)
    mine = [p for p in r.json() if p["id"] == patient_id]
    assert mine and mine[0]["active_regimen_count"] == 1

    r = client.patch(
        f"/api/v1/patients/{patient_id}/regimens/{regimen_id}",
        headers=clinician_headers,
        json={"end_date": "2024-06-01"},
    )
    assert r.status_code == 200
    assert r.json()["end_date"] == "2024-06-01"

    r = client.get(
        f"/api/v1/patients/{patient_id}/regimens",
        params={"active_only": True},
        headers=clinician_headers,
    )
    assert all(reg["id"] != regimen_id for reg in r.json())


def test_unknown_patient_id_404s(client, clinician_headers):
    r = client.get("/api/v1/patients/00000000-0000-0000-0000-000000000000", headers=clinician_headers)
    assert r.status_code == 404
