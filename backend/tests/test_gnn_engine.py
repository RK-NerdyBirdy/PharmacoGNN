from __future__ import annotations

import pytest
import torch

from app.services import gnn_engine as ge


@pytest.fixture(autouse=True)
def _isolate_gnn_engine_globals(client):
    """Snapshot/restore module-level state around each test in this file.

    `client` is depended on (not just imported) specifically to force
    gnn_engine.initialize() to have already run before we snapshot -- these
    tests overwrite DRUG2IDX/EDGE_INDEX_DICT/etc. with small fake graphs, and
    without this, that pollution would leak into test_predict.py/test_patients.py
    if this file happened to run before anything else touches `client`.
    """
    snapshot = {
        name: getattr(ge, name)
        for name in ("DRUG2IDX", "CID_TO_NAME", "PROTEIN2IDX", "IDX2PROTEIN", "PROTEIN_TO_NAME", "EDGE_INDEX_DICT")
    }
    yield
    for name, value in snapshot.items():
        setattr(ge, name, value)


def _set_fake_graph(edge_index_dict):
    ge.DRUG2IDX = {"DRUG_A": 0, "DRUG_B": 1, "DRUG_C": 2}
    ge.CID_TO_NAME = {"DRUG_A": "Drug A", "DRUG_B": "Drug B", "DRUG_C": "Drug C"}
    ge.PROTEIN2IDX = {"P1": 0, "P2": 1, "P3": 2}
    ge.IDX2PROTEIN = {0: "P1", 1: "P2", 2: "P3"}
    ge.PROTEIN_TO_NAME = {"P1": "ProteinOne", "P2": "ProteinTwo", "P3": "ProteinThree"}
    ge.EDGE_INDEX_DICT = edge_index_dict


def test_find_bridging_proteins_direct_shared_target():
    _set_fake_graph(
        {
            ("drug", "targets", "protein"): torch.tensor([[0, 1], [0, 0]]),  # DRUG_A->P1, DRUG_B->P1
            ("protein", "interacts", "protein"): torch.tensor([[], []], dtype=torch.long),
        }
    )
    result = ge.find_bridging_proteins("DRUG_A", "DRUG_B")
    assert result["data_available"] is True
    protein_nodes = [n for n in result["nodes"] if n["type"] == "protein"]
    assert len(protein_nodes) == 1
    assert protein_nodes[0]["label"] == "ProteinOne"
    assert protein_nodes[0]["id"] == "protein:P1"
    assert {e["source"] for e in result["edges"]} == {"drug:DRUG_A", "drug:DRUG_B"}


def test_find_bridging_proteins_ppi_hop():
    _set_fake_graph(
        {
            ("drug", "targets", "protein"): torch.tensor([[0, 1], [0, 1]]),  # DRUG_A->P1, DRUG_B->P2
            ("protein", "interacts", "protein"): torch.tensor([[0], [1]]),  # P1 -> P2
        }
    )
    result = ge.find_bridging_proteins("DRUG_A", "DRUG_B")
    assert result["data_available"] is True
    labels = {n["label"] for n in result["nodes"]}
    assert labels == {"Drug A", "Drug B", "ProteinOne", "ProteinTwo"}
    assert any(e["label"] == "interacts" for e in result["edges"])


def test_find_bridging_proteins_no_connection():
    _set_fake_graph(
        {
            ("drug", "targets", "protein"): torch.tensor([[0, 1], [0, 2]]),  # DRUG_A->P1, DRUG_B->P3
            ("protein", "interacts", "protein"): torch.tensor([[], []], dtype=torch.long),  # no PPI edges
        }
    )
    result = ge.find_bridging_proteins("DRUG_A", "DRUG_B")
    assert result == {"nodes": [], "edges": [], "data_available": False}


def test_find_bridging_proteins_degraded_mode_returns_empty():
    _set_fake_graph(None)
    result = ge.find_bridging_proteins("DRUG_A", "DRUG_B")
    assert result == {"nodes": [], "edges": [], "data_available": False}


def test_find_bridging_proteins_unknown_cid_returns_empty():
    _set_fake_graph({("drug", "targets", "protein"): torch.tensor([[0], [0]])})
    result = ge.find_bridging_proteins("NOT_A_REAL_DRUG", "DRUG_B")
    assert result == {"nodes": [], "edges": [], "data_available": False}


def test_drug_name_falls_back_to_cid_when_unknown():
    _set_fake_graph(None)
    assert ge.drug_name("SOME_UNKNOWN_CID") == "SOME_UNKNOWN_CID"
    assert ge.drug_name("DRUG_A") == "Drug A"


def test_protein_name_falls_back_to_id_when_unknown():
    _set_fake_graph(None)
    assert ge.protein_name("SOME_UNKNOWN_PROTEIN") == "SOME_UNKNOWN_PROTEIN"
    assert ge.protein_name("P1") == "ProteinOne"
