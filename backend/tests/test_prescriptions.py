"""Structured prescription import (Phase C).

Every drug that ends up in a PatientRegimen row must be one of the model's
645 in-vocabulary CIDs -- otherwise it can never be scored, substituted, or
explained, and a regimen that silently dropped an unresolvable drug would
make every later interaction report on that patient falsely reassuring. All
tests here exist to pin that guarantee down at the API boundary.

Real in-vocabulary drugs used below (from gnn_engine's 645-CID vocabulary):
  Aspirin    -> CID000002244
  Metformin  -> CID000004091
  Losartan   -> CID000003961
"Definitely Not A Real Drug" is guaranteed absent from the vocabulary.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

ASPIRIN_CID = "CID000002244"
METFORMIN_CID = "CID000004091"
FAKE_DRUG = "Definitely Not A Real Drug"


def _prescription_payload(**overrides) -> dict:
    body = {
        "prescriber_name": "Dr. External, MD",
        "issued_date": "2024-01-01",
        "allow_partial": False,
        "items": [
            {
                "drug_name": "Aspirin",
                "pubchem_cid": ASPIRIN_CID,
                "dosage": "81mg",
                "frequency": "once daily",
                "route": "oral",
                "start_date": "2024-01-01",
            },
            {
                "drug_name": "Metformin",
                "dosage": "500mg",
                "frequency": "twice daily",
                "route": "oral",
                "start_date": "2024-01-01",
            },
        ],
    }
    body.update(overrides)
    return body


def test_import_resolves_by_cid_and_by_name(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/prescriptions",
        headers=clinician_headers,
        json=_prescription_payload(),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["committed"] is True
    assert body["unresolved"] == []
    assert len(body["created"]) == 2

    cids = {row["pubchem_cid"] for row in body["created"]}
    assert cids == {ASPIRIN_CID, METFORMIN_CID}

    for row in body["created"]:
        assert row["external_prescriber_name"] == "Dr. External, MD"
        assert row["import_batch_id"] is not None
    # Both rows share the same import batch.
    assert body["created"][0]["import_batch_id"] == body["created"][1]["import_batch_id"]


def test_import_unresolved_item_aborts_without_allow_partial(
    client: TestClient, clinician_headers, patient
):
    patient_id = patient["patient_id"]

    payload = _prescription_payload(
        allow_partial=False,
        items=[
            {"drug_name": "Aspirin", "pubchem_cid": ASPIRIN_CID, "start_date": "2024-01-01"},
            {"drug_name": FAKE_DRUG, "start_date": "2024-01-01"},
        ],
    )
    r = client.post(
        f"/api/v1/patients/{patient_id}/prescriptions", headers=clinician_headers, json=payload
    )
    assert r.status_code == 201, r.text
    body = r.json()

    assert body["committed"] is False
    assert body["created"] == []
    assert len(body["unresolved"]) == 1
    assert body["unresolved"][0]["drug_name"] == FAKE_DRUG
    assert body["unresolved"][0]["reason"] == "not_in_vocabulary"

    # Nothing was actually written -- the resolvable item was not committed either.
    r = client.get(f"/api/v1/patients/{patient_id}/regimens", headers=clinician_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_import_unresolved_item_with_allow_partial_commits_the_rest(
    client: TestClient, clinician_headers, patient
):
    patient_id = patient["patient_id"]

    payload = _prescription_payload(
        allow_partial=True,
        items=[
            {"drug_name": "Aspirin", "pubchem_cid": ASPIRIN_CID, "start_date": "2024-01-01"},
            {"drug_name": FAKE_DRUG, "start_date": "2024-01-01"},
        ],
    )
    r = client.post(
        f"/api/v1/patients/{patient_id}/prescriptions", headers=clinician_headers, json=payload
    )
    assert r.status_code == 201, r.text
    body = r.json()

    assert body["committed"] is True
    assert len(body["created"]) == 1
    assert body["created"][0]["pubchem_cid"] == ASPIRIN_CID
    assert len(body["unresolved"]) == 1
    assert body["unresolved"][0]["drug_name"] == FAKE_DRUG

    r = client.get(f"/api/v1/patients/{patient_id}/regimens", headers=clinician_headers)
    assert len(r.json()) == 1


def test_manual_add_rejects_unresolvable_drug(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/regimens",
        headers=clinician_headers,
        json={"drug_name": FAKE_DRUG, "start_date": "2024-01-01"},
    )
    assert r.status_code == 422

    r = client.get(f"/api/v1/patients/{patient_id}/regimens", headers=clinician_headers)
    assert r.json() == []


def test_manual_add_resolves_by_cid(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/regimens",
        headers=clinician_headers,
        json={"drug_name": "whatever, cid wins", "pubchem_cid": ASPIRIN_CID, "start_date": "2024-01-01"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["pubchem_cid"] == ASPIRIN_CID


def test_hard_delete_distinct_from_discontinue(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/regimens",
        headers=clinician_headers,
        json={"drug_name": "Aspirin", "pubchem_cid": ASPIRIN_CID, "start_date": "2024-01-01"},
    )
    assert r.status_code == 201
    regimen_id = r.json()["id"]

    # Discontinue (PATCH end_date) keeps the row -- it just drops out of active_only.
    r = client.patch(
        f"/api/v1/patients/{patient_id}/regimens/{regimen_id}",
        headers=clinician_headers,
        json={"end_date": "2024-06-01"},
    )
    assert r.status_code == 200

    r = client.get(f"/api/v1/patients/{patient_id}/regimens", headers=clinician_headers)
    assert any(row["id"] == regimen_id for row in r.json())

    # Hard delete actually erases it.
    r = client.delete(
        f"/api/v1/patients/{patient_id}/regimens/{regimen_id}", headers=clinician_headers
    )
    assert r.status_code == 204

    r = client.get(f"/api/v1/patients/{patient_id}/regimens", headers=clinician_headers)
    assert all(row["id"] != regimen_id for row in r.json())

    # Deleting again 404s -- it's really gone, not just soft-hidden.
    r = client.delete(
        f"/api/v1/patients/{patient_id}/regimens/{regimen_id}", headers=clinician_headers
    )
    assert r.status_code == 404


def test_unassigned_clinician_gets_404_not_403(
    client: TestClient, clinician_headers, other_clinician_headers, patient
):
    patient_id = patient["patient_id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/prescriptions",
        headers=other_clinician_headers,
        json=_prescription_payload(),
    )
    assert r.status_code == 404

    r = client.delete(
        f"/api/v1/patients/{patient_id}/regimens/00000000-0000-0000-0000-000000000000",
        headers=other_clinician_headers,
    )
    assert r.status_code == 404


def test_patient_cannot_import_or_delete(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/regimens",
        headers=clinician_headers,
        json={"drug_name": "Aspirin", "pubchem_cid": ASPIRIN_CID, "start_date": "2024-01-01"},
    )
    assert r.status_code == 201
    regimen_id = r.json()["id"]

    r = client.post(
        f"/api/v1/patients/{patient_id}/prescriptions",
        headers=patient["headers"],
        json=_prescription_payload(),
    )
    assert r.status_code == 403

    r = client.delete(
        f"/api/v1/patients/{patient_id}/regimens/{regimen_id}", headers=patient["headers"]
    )
    assert r.status_code == 403
