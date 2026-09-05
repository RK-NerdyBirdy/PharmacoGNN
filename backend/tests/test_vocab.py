from __future__ import annotations


def test_search_drugs(client, clinician_headers):
    r = client.get("/api/v1/vocab/drugs", params={"q": "acid", "limit": 5}, headers=clinician_headers)
    assert r.status_code == 200
    results = r.json()
    assert 0 < len(results) <= 5
    for entry in results:
        assert "acid" in entry["name"].lower()


def test_search_drugs_pagination(client, clinician_headers):
    page1 = client.get(
        "/api/v1/vocab/drugs", params={"limit": 10, "offset": 0}, headers=clinician_headers
    ).json()
    page2 = client.get(
        "/api/v1/vocab/drugs", params={"limit": 10, "offset": 10}, headers=clinician_headers
    ).json()
    assert {d["cid"] for d in page1}.isdisjoint({d["cid"] for d in page2})


def test_get_drug_by_cid(client, clinician_headers):
    r = client.get("/api/v1/vocab/drugs/CID000000085", headers=clinician_headers)
    assert r.status_code == 200
    assert r.json()["cid"] == "CID000000085"


def test_get_unknown_drug_404(client, clinician_headers):
    r = client.get("/api/v1/vocab/drugs/CID_NOT_REAL", headers=clinician_headers)
    assert r.status_code == 404


def test_list_adverse_effects(client, clinician_headers):
    r = client.get("/api/v1/vocab/adverse-effects", headers=clinician_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 50
    assert sum(1 for e in body if e["female_weighted"]) == 35


def test_get_adverse_effect_by_cui(client, clinician_headers):
    r = client.get("/api/v1/vocab/adverse-effects/C0040034", headers=clinician_headers)
    assert r.status_code == 200
    assert r.json()["name"] == "thrombocytopenia"


def test_get_unknown_adverse_effect_404(client, clinician_headers):
    r = client.get("/api/v1/vocab/adverse-effects/NOT_A_REAL_CUI", headers=clinician_headers)
    assert r.status_code == 404


def test_vocab_requires_auth(client):
    assert client.get("/api/v1/vocab/drugs").status_code == 401
    assert client.get("/api/v1/vocab/adverse-effects").status_code == 401
