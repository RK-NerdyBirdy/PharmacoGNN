from __future__ import annotations

DRUG_A = "CID000000085"
DRUG_B = "CID000000119"
DRUG_C = "CID000000143"


def test_pairwise_unknown_cid_404(client, clinician_headers):
    r = client.post(
        "/api/v1/predict/pairwise",
        headers=clinician_headers,
        json={"drug_a_cid": "CID_DOES_NOT_EXIST", "drug_b_cid": DRUG_A},
    )
    assert r.status_code == 404


def test_pairwise_real_pair_shape(client, clinician_headers):
    r = client.post(
        "/api/v1/predict/pairwise", headers=clinician_headers, json={"drug_a_cid": DRUG_A, "drug_b_cid": DRUG_B}
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["adverse_effects"]) == 50
    assert "degraded_mode" in body
    assert body["top_adverse_effect"] == body["adverse_effects"][0]["name"]
    assert body["top_risk_score"] == body["adverse_effects"][0]["risk_score"]

    scores = [e["risk_score"] for e in body["adverse_effects"]]
    assert scores == sorted(scores, reverse=True)
    assert sum(1 for e in body["adverse_effects"] if e["female_weighted"]) == 35


def test_pairwise_female_bias_only_scales_female_weighted_adrs(client, clinician_headers):
    r_base = client.post(
        "/api/v1/predict/pairwise", headers=clinician_headers, json={"drug_a_cid": DRUG_A, "drug_b_cid": DRUG_B}
    ).json()
    r_female = client.post(
        "/api/v1/predict/pairwise",
        headers=clinician_headers,
        json={"drug_a_cid": DRUG_A, "drug_b_cid": DRUG_B, "patient_sex": "FEMALE"},
    ).json()

    by_cui_base = {e["cui"]: e["risk_score"] for e in r_base["adverse_effects"]}
    by_cui_female = {e["cui"]: e["risk_score"] for e in r_female["adverse_effects"]}
    non_female_weighted = [e["cui"] for e in r_base["adverse_effects"] if not e["female_weighted"]]

    for cui in non_female_weighted:
        assert by_cui_base[cui] == by_cui_female[cui]


def test_regimen_requires_at_least_two_drugs(client, clinician_headers):
    r = client.post("/api/v1/predict/regimen", headers=clinician_headers, json={"drug_cids": [DRUG_A]})
    assert r.status_code == 422


def test_regimen_matrix_shape_and_symmetry(client, clinician_headers):
    cids = [DRUG_A, DRUG_B, DRUG_C]
    r = client.post("/api/v1/predict/regimen", headers=clinician_headers, json={"drug_cids": cids})
    assert r.status_code == 200
    body = r.json()

    n = len(cids)
    matrix = body["interaction_matrix"]
    assert len(matrix) == n and all(len(row) == n for row in matrix)
    for i in range(n):
        assert matrix[i][i] == 0.0
        for j in range(n):
            assert matrix[i][j] == matrix[j][i]

    assert len(body["pairwise_flags"]) == n * (n - 1) // 2
    # drug_disease_flags always [] until a reference file exists (see services/drug_disease.py)
    assert body["drug_disease_flags"] == []


def test_regimen_unknown_cid_404(client, clinician_headers):
    r = client.post(
        "/api/v1/predict/regimen", headers=clinician_headers, json={"drug_cids": [DRUG_A, "CID_NOT_REAL"]}
    )
    assert r.status_code == 404


def test_substitute_response_invariants(client, clinician_headers):
    r = client.post(
        "/api/v1/predict/substitute", headers=clinician_headers, json={"drug_a_cid": DRUG_A, "drug_b_cid": DRUG_B}
    )
    assert r.status_code == 200
    body = r.json()

    assert body["substitution_recommended"] == (body["original_top_risk_score"] > 75.0)
    if not body["substitution_recommended"]:
        assert body["alternatives"] == []
    assert len(body["alternatives"]) <= 3

    for alt in body["alternatives"]:
        assert alt["cid"] not in (DRUG_A, DRUG_B)
        assert "Unknown Drug" not in alt["name"]


def test_predict_endpoints_require_auth(client):
    assert client.post("/api/v1/predict/pairwise", json={"drug_a_cid": DRUG_A, "drug_b_cid": DRUG_B}).status_code == 401
    assert client.post("/api/v1/predict/regimen", json={"drug_cids": [DRUG_A, DRUG_B]}).status_code == 401
    assert client.post("/api/v1/predict/substitute", json={"drug_a_cid": DRUG_A, "drug_b_cid": DRUG_B}).status_code == 401
