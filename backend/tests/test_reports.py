"""Interaction report generation, retrieval, PDF download, and soft-delete.

Generation runs as a FastAPI BackgroundTask. Starlette's TestClient executes
background tasks synchronously as part of the request/response cycle (unlike
a real deployed server, where they run after the response is flushed) --
so in these tests, a report is already COMPLETE by the time POST returns,
with no polling loop needed.

DRUG_A/DRUG_B/DRUG_C match tests/test_predict.py's real in-vocabulary CIDs.
Regardless of whether this pair happens to be high-risk, generation must
still succeed: OPENROUTER_API_KEY is not configured in this test
environment, and report_generation.py is specifically designed to skip a
pair's LLM explanation (not fail the whole report) when that call errors.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

DRUG_A = "CID000000085"
DRUG_B = "CID000000119"
DRUG_C = "CID000000143"


def _add_active_regimen(client: TestClient, clinician_headers, patient_id, cid: str) -> str:
    r = client.post(
        f"/api/v1/patients/{patient_id}/regimens",
        headers=clinician_headers,
        json={"drug_name": "whatever, cid wins", "pubchem_cid": cid, "start_date": "2024-01-01"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _generate_report(client: TestClient, clinician_headers, patient_id) -> dict:
    r = client.post(f"/api/v1/patients/{patient_id}/reports", headers=clinician_headers)
    assert r.status_code == 202, r.text
    return r.json()


def test_generate_report_completes_synchronously_in_tests(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_A)
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_B)

    accepted = _generate_report(client, clinician_headers, patient_id)
    assert accepted["status"] == "pending"
    report_id = accepted["id"]

    r = client.get(f"/api/v1/reports/{report_id}", headers=clinician_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["status"] == "complete"
    assert body["disclaimer"] == "Not to be taken without clinical supervision."
    assert body["model_status"] is not None
    assert body["model_status"]["verified"] is False
    assert {item["pubchem_cid"] for item in body["regimen_snapshot"]} == {DRUG_A, DRUG_B}
    assert body["unresolved_drugs"] == []
    assert body["summary"]["drug_count"] == 2
    assert len(body["interaction_matrix"]) == 2
    assert len(body["pairwise"]) == 1
    pair = body["pairwise"][0]
    assert {pair["drug_a_cid"], pair["drug_b_cid"]} == {DRUG_A, DRUG_B}
    assert body["file_available"] is True
    assert body["error_message"] is None


def test_generate_requires_two_active_drugs(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_A)

    r = client.post(f"/api/v1/patients/{patient_id}/reports", headers=clinician_headers)
    assert r.status_code == 422


def test_discontinued_drug_excluded_from_report(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]
    stopped_id = _add_active_regimen(client, clinician_headers, patient_id, DRUG_A)
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_B)
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_C)

    r = client.patch(
        f"/api/v1/patients/{patient_id}/regimens/{stopped_id}",
        headers=clinician_headers,
        json={"end_date": "2024-06-01"},
    )
    assert r.status_code == 200

    accepted = _generate_report(client, clinician_headers, patient_id)
    r = client.get(f"/api/v1/reports/{accepted['id']}", headers=clinician_headers)
    body = r.json()

    assert body["status"] == "complete"
    cids = {item["pubchem_cid"] for item in body["regimen_snapshot"]}
    assert cids == {DRUG_B, DRUG_C}
    assert DRUG_A not in cids


def test_list_reports(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_A)
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_B)
    accepted = _generate_report(client, clinician_headers, patient_id)

    r = client.get(f"/api/v1/patients/{patient_id}/reports", headers=clinician_headers)
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()]
    assert accepted["id"] in ids


def test_pdf_download_and_regeneration_after_disk_wipe(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_A)
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_B)
    accepted = _generate_report(client, clinician_headers, patient_id)
    report_id = accepted["id"]

    r = client.get(f"/api/v1/reports/{report_id}/pdf", headers=clinician_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")

    # Simulate the ephemeral-disk wipe the docs warn about: the file is gone,
    # but the analysis (payload, in Postgres) is not -- download must still
    # succeed by re-rendering rather than 404ing.
    from app.core.config import settings

    pdf_path = settings.REPORTS_DIR / f"{report_id}.pdf"
    assert pdf_path.exists()
    pdf_path.unlink()

    detail = client.get(f"/api/v1/reports/{report_id}", headers=clinician_headers).json()
    assert detail["file_available"] is False

    r2 = client.get(f"/api/v1/reports/{report_id}/pdf", headers=clinician_headers)
    assert r2.status_code == 200
    assert r2.content.startswith(b"%PDF")
    assert pdf_path.exists()


def test_delete_report_soft_deletes(client: TestClient, clinician_headers, patient):
    patient_id = patient["patient_id"]
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_A)
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_B)
    accepted = _generate_report(client, clinician_headers, patient_id)
    report_id = accepted["id"]

    r = client.delete(f"/api/v1/reports/{report_id}", headers=clinician_headers)
    assert r.status_code == 204

    assert client.get(f"/api/v1/reports/{report_id}", headers=clinician_headers).status_code == 404
    assert client.get(f"/api/v1/reports/{report_id}/pdf", headers=clinician_headers).status_code == 404

    ids = [item["id"] for item in client.get(
        f"/api/v1/patients/{patient_id}/reports", headers=clinician_headers
    ).json()]
    assert report_id not in ids

    # Deleting again 404s -- it's really gone from the accessible surface.
    assert client.delete(f"/api/v1/reports/{report_id}", headers=clinician_headers).status_code == 404


def test_unassigned_clinician_gets_404_not_403(
    client: TestClient, clinician_headers, other_clinician_headers, patient
):
    patient_id = patient["patient_id"]
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_A)
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_B)
    accepted = _generate_report(client, clinician_headers, patient_id)
    report_id = accepted["id"]

    assert client.post(
        f"/api/v1/patients/{patient_id}/reports", headers=other_clinician_headers
    ).status_code == 404
    assert client.get(
        f"/api/v1/patients/{patient_id}/reports", headers=other_clinician_headers
    ).status_code == 404
    assert client.get(f"/api/v1/reports/{report_id}", headers=other_clinician_headers).status_code == 404
    assert client.get(f"/api/v1/reports/{report_id}/pdf", headers=other_clinician_headers).status_code == 404
    assert client.delete(f"/api/v1/reports/{report_id}", headers=other_clinician_headers).status_code == 404


def test_patient_can_read_own_reports_but_not_generate_or_delete(
    client: TestClient, clinician_headers, patient
):
    patient_id = patient["patient_id"]
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_A)
    _add_active_regimen(client, clinician_headers, patient_id, DRUG_B)
    accepted = _generate_report(client, clinician_headers, patient_id)
    report_id = accepted["id"]

    assert client.get(
        f"/api/v1/patients/{patient_id}/reports", headers=patient["headers"]
    ).status_code == 200
    assert client.get(f"/api/v1/reports/{report_id}", headers=patient["headers"]).status_code == 200
    assert client.get(f"/api/v1/reports/{report_id}/pdf", headers=patient["headers"]).status_code == 200

    assert client.post(
        f"/api/v1/patients/{patient_id}/reports", headers=patient["headers"]
    ).status_code == 403
    assert client.delete(f"/api/v1/reports/{report_id}", headers=patient["headers"]).status_code == 403


def test_unknown_report_id_404s(client: TestClient, clinician_headers):
    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/reports/{fake_id}", headers=clinician_headers).status_code == 404
    assert client.get(f"/api/v1/reports/{fake_id}/pdf", headers=clinician_headers).status_code == 404
    assert client.delete(f"/api/v1/reports/{fake_id}", headers=clinician_headers).status_code == 404
