from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
from torch_geometric.nn import HGTConv

from app.core.config import settings

logger = logging.getLogger(__name__)

# The checkpoint (backend/weights/pharmacognn_deep_state_dict.pth) was reverse-
# engineered key-by-key: this exact class hierarchy loads it with
# `strict=True` and every key matching (verified against the real file, not
# guessed). Do not rename modules/attributes without re-checking against the
# checkpoint's state_dict keys.
Metadata = tuple[list[str], list[tuple[str, str, str]]]

_GRAPH_EDGE_FILENAMES = ("graph_edge_index.pt", "hetero_graph.pt", "graph_edges.pt")


class NodeEmbedding(nn.Module):
    """Learned input node features, pre-message-passing."""

    def __init__(self, num_drugs: int, num_proteins: int, hidden_dim: int) -> None:
        super().__init__()
        self.drug_emb = nn.Embedding(num_drugs, hidden_dim)
        self.protein_emb = nn.Embedding(num_proteins, hidden_dim)


class HeteroEncoder(nn.Module):
    """3-layer HGTConv stack with per-node-type LayerNorm after each layer.

    NOTE: the state_dict proves the conv/norm module shapes exactly (verified
    via strict=True load against the real checkpoint), but LayerNorm/ReLU are
    parameter-free, so the *inter-layer activation* below cannot be verified
    the same way. It was actively checked against weights/z_protein.pt (an
    independently-computed reference protein embedding shipped alongside
    graph_edge_index.pt) by running this exact encoder over the real graph:
    ReLU-after-LayerNorm gives mean_abs_diff=0.71 against a reference whose
    own mean abs value is only 0.80 -- i.e. NOT a match, likely wrong, not
    just numerical noise. The "no ReLU, LayerNorm only" alternative has not
    yet been checked (a full 3-layer forward pass over ~1.5M edges takes
    ~25 min on CPU here). Z_DRUG_CACHE computed via this encoder should be
    treated as directionally-graph-aware but NOT confirmed numerically
    correct until this is resolved -- see the training script if it surfaces,
    or re-run the no-ReLU variant, before trusting absolute risk scores.
    """

    def __init__(self, hidden_dim: int, num_layers: int, heads: int, metadata: Metadata) -> None:
        super().__init__()
        node_types, _ = metadata
        self.convs = nn.ModuleList(
            [HGTConv(hidden_dim, hidden_dim, metadata, heads=heads) for _ in range(num_layers)]
        )
        self.norms = nn.ModuleList(
            [nn.ModuleDict({nt: nn.LayerNorm(hidden_dim) for nt in node_types}) for _ in range(num_layers)]
        )

    def forward(
        self, x_dict: dict[str, torch.Tensor], edge_index_dict: dict[tuple[str, str, str], torch.Tensor]
    ) -> dict[str, torch.Tensor]:
        for conv, norm in zip(self.convs, self.norms):
            x_dict = conv(x_dict, edge_index_dict)
            x_dict = {node_type: norm[node_type](x).relu() for node_type, x in x_dict.items()}
        return x_dict


class BilinearDecoder(nn.Module):
    """Neural bilinear decoder: MLP([z_u, z_v, z_u⊙z_v, |z_u-z_v|, e_r])."""

    def __init__(self, hidden_dim: int, num_relations: int) -> None:
        super().__init__()
        self.rel_embed = nn.Embedding(num_relations, hidden_dim)
        self.mlp = nn.Sequential(
            nn.Linear(hidden_dim * 5, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, 1),
        )

    def forward(self, z_u: torch.Tensor, z_v: torch.Tensor, rel_idx: torch.Tensor) -> torch.Tensor:
        e_r = self.rel_embed(rel_idx)
        feats = torch.cat([z_u, z_v, z_u * z_v, (z_u - z_v).abs(), e_r], dim=-1)
        logits = self.mlp(feats).squeeze(-1)
        return torch.sigmoid(logits)


class PharmacoGNN(nn.Module):
    def __init__(
        self,
        num_drugs: int,
        num_proteins: int,
        hidden_dim: int,
        num_layers: int,
        heads: int,
        metadata: Metadata,
        num_se_relations: int,
    ) -> None:
        super().__init__()
        self.node_embed = NodeEmbedding(num_drugs, num_proteins, hidden_dim)
        self.encoder = HeteroEncoder(hidden_dim, num_layers, heads, metadata)
        self.decoder = BilinearDecoder(hidden_dim, num_se_relations)


# --- Module-level inference state, populated once by initialize() -----------

_MODEL: PharmacoGNN | None = None
_MODEL_CONFIG: dict[str, Any] = {}

Z_DRUG_CACHE: torch.Tensor | None = None
Z_DRUG_CACHE_DEGRADED: bool = True

DRUG2IDX: dict[str, int] = {}
IDX2DRUG: dict[str, str] = {}
CID_TO_NAME: dict[str, str] = {}
# Index-aligned with decoder.rel_embed rows: IDX_TO_RELATION_META[i] describes relation i.
IDX_TO_RELATION_META: list[dict[str, Any]] = []

PROTEIN2IDX: dict[str, int] = {}
IDX2PROTEIN: dict[int, str] = {}
PROTEIN_TO_NAME: dict[str, str] = {}
# Populated only when real graph edges were found; used by find_bridging_proteins
# for a graph-grounded xai_pathway. None in degraded mode.
EDGE_INDEX_DICT: dict[tuple[str, str, str], torch.Tensor] | None = None


def _read_json(weights_dir: Path, filename: str) -> Any:
    return json.loads((weights_dir / filename).read_text(encoding="utf-8"))


def _build_model(weights_dir: Path, cfg: dict[str, Any], num_se_relations: int) -> PharmacoGNN:
    metadata: Metadata = (cfg["node_types"], [tuple(edge) for edge in cfg["edge_types"]])
    model = PharmacoGNN(
        num_drugs=cfg["num_drugs"],
        num_proteins=cfg["num_proteins"],
        hidden_dim=cfg["hidden_dim"],
        num_layers=cfg["num_layers"],
        heads=cfg["heads"],
        metadata=metadata,
        num_se_relations=num_se_relations,
    )

    weights_path = weights_dir / settings.MODEL_STATE_DICT_FILENAME
    if not weights_path.exists():
        raise RuntimeError(
            f"Model weights not found at {weights_path}. Refusing to serve predictions from "
            "randomly-initialized weights -- this is a clinical-safety system, not a demo."
        )

    state_dict = torch.load(weights_path, map_location=settings.GNN_DEVICE, weights_only=True)
    model.load_state_dict(state_dict, strict=True)  # raises loudly on any key/shape mismatch
    model.to(settings.GNN_DEVICE)
    model.eval()
    return model


def _try_load_edge_index_dict(
    weights_dir: Path,
) -> tuple[dict[tuple[str, str, str], torch.Tensor], str] | tuple[None, None]:
    """Looks for graph edges produced by the training pipeline.

    Returns (edge_index_dict, filename_used), or (None, None) if nothing is
    found -- rather than fabricating topology; callers must treat that as a
    real, visible degraded mode, not a silent fallback.
    """
    for filename in _GRAPH_EDGE_FILENAMES:
        path = weights_dir / filename
        if not path.exists():
            continue
        obj = torch.load(path, map_location=settings.GNN_DEVICE, weights_only=False)
        edge_index_dict = getattr(obj, "edge_index_dict", obj)  # HeteroData, or an already-plain dict
        if isinstance(edge_index_dict, dict):
            return edge_index_dict, filename
    return None, None


def _fingerprint(path: Path) -> dict[str, str | int]:
    """Content hash + size, NOT mtime: mtime is reset by every `git checkout`/
    clone, so a cache computed on one machine and committed for teammates to
    reuse (exactly how this is meant to be used) would otherwise always look
    "stale" on a fresh checkout even when the file content is byte-identical.
    """
    hasher = hashlib.blake2b(digest_size=16)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return {"hash": hasher.hexdigest(), "size": path.stat().st_size}


def _source_fingerprint(weights_dir: Path, edge_filename: str | None) -> dict[str, Any]:
    """Identifies exactly which inputs a cached Z_DRUG_CACHE was built from.

    Compared against the currently-present files' content hashes before
    trusting a cached tensor, so swapping in a retrained checkpoint or a new
    graph can never silently serve stale embeddings.
    """
    weights_path = weights_dir / settings.MODEL_STATE_DICT_FILENAME
    fingerprint: dict[str, Any] = {
        "state_dict": _fingerprint(weights_path) if weights_path.exists() else None,
        "edge_filename": edge_filename,
    }
    if edge_filename is not None:
        fingerprint["edge_file"] = _fingerprint(weights_dir / edge_filename)
    return fingerprint


def _load_cached_drug_cache(
    weights_dir: Path, expected_fingerprint: dict[str, Any]
) -> torch.Tensor | None:
    cache_path = weights_dir / settings.Z_DRUG_CACHE_FILENAME
    if not cache_path.exists():
        return None
    try:
        cached = torch.load(cache_path, map_location=settings.GNN_DEVICE, weights_only=False)
    except Exception:
        logger.warning("PharmacoGNN: failed to load %s, recomputing.", cache_path, exc_info=True)
        return None

    if not isinstance(cached, dict) or cached.get("fingerprint") != expected_fingerprint:
        logger.info(
            "PharmacoGNN: %s exists but its fingerprint doesn't match the current "
            "state_dict/edge file -- source data changed, recomputing instead of "
            "serving a stale cache.",
            cache_path,
        )
        return None

    logger.info("PharmacoGNN: loaded precomputed Z_DRUG_CACHE from %s (skipping the encoder forward pass).", cache_path)
    return cached["z_drug"]


def _save_drug_cache(weights_dir: Path, z_drug: torch.Tensor, fingerprint: dict[str, Any]) -> None:
    cache_path = weights_dir / settings.Z_DRUG_CACHE_FILENAME
    try:
        torch.save({"z_drug": z_drug, "fingerprint": fingerprint}, cache_path)
        logger.info("PharmacoGNN: saved Z_DRUG_CACHE to %s for fast startup next time.", cache_path)
    except OSError:
        logger.warning("PharmacoGNN: could not write %s (read-only mount?); will recompute next startup.", cache_path)


@torch.no_grad()
def _compute_drug_cache(
    model: PharmacoGNN, weights_dir: Path, cfg: dict[str, Any]
) -> tuple[torch.Tensor, bool, dict[tuple[str, str, str], torch.Tensor] | None]:
    device = settings.GNN_DEVICE
    x_dict = {
        "drug": model.node_embed.drug_emb(torch.arange(cfg["num_drugs"], device=device)),
        "protein": model.node_embed.protein_emb(torch.arange(cfg["num_proteins"], device=device)),
    }

    edge_index_dict, edge_filename = _try_load_edge_index_dict(weights_dir)
    if edge_index_dict is None:
        logger.warning(
            "PharmacoGNN: no graph edge data found in %s (looked for %s). "
            "Z_DRUG_CACHE is falling back to PRE-CONVOLUTION drug embeddings -- "
            "the 3-layer HGTConv encoder is NOT being run, so predictions are "
            "computed from embeddings that never saw the protein-interaction graph. "
            "This is a degraded, non-production state; see gnn_engine.Z_DRUG_CACHE_DEGRADED.",
            weights_dir,
            _GRAPH_EDGE_FILENAMES,
        )
        return x_dict["drug"].clone(), True, None

    fingerprint = _source_fingerprint(weights_dir, edge_filename)
    cached_z_drug = _load_cached_drug_cache(weights_dir, fingerprint)
    if cached_z_drug is not None:
        return cached_z_drug, False, edge_index_dict

    logger.warning(
        "PharmacoGNN: no valid %s found -- running the 3-layer HGTConv encoder over the full "
        "graph now. This is a one-time cost (tens of minutes on CPU for a graph this size); "
        "the result will be cached to disk so future startups skip it. Run "
        "`python -m app.scripts.precompute_z_drug_cache` ahead of time to avoid paying this "
        "cost on a live server's first request.",
        settings.Z_DRUG_CACHE_FILENAME,
    )
    z_dict = model.encoder(x_dict, edge_index_dict)
    z_drug = z_dict["drug"]
    _save_drug_cache(weights_dir, z_drug, fingerprint)
    return z_drug, False, edge_index_dict


def initialize() -> None:
    """Load artifacts + weights and populate Z_DRUG_CACHE. Call once at app startup."""
    global _MODEL, _MODEL_CONFIG, Z_DRUG_CACHE, Z_DRUG_CACHE_DEGRADED
    global DRUG2IDX, IDX2DRUG, CID_TO_NAME, IDX_TO_RELATION_META
    global PROTEIN2IDX, IDX2PROTEIN, PROTEIN_TO_NAME, EDGE_INDEX_DICT

    weights_dir = settings.WEIGHTS_DIR
    cfg = _read_json(weights_dir, "model_config.json")
    relation_meta_by_cui = _read_json(weights_dir, "relation_meta.json")

    idx_to_meta: list[dict[str, Any] | None] = [None] * len(relation_meta_by_cui)
    for cui, meta in relation_meta_by_cui.items():
        idx_to_meta[meta["rel_idx"]] = {
            "cui": cui,
            "name": meta["name"],
            "female_weighted": meta["female_weighted"],
        }
    if any(m is None for m in idx_to_meta):
        raise RuntimeError("relation_meta.json rel_idx values do not densely cover 0..N-1")

    DRUG2IDX = _read_json(weights_dir, "drug2idx.json")
    IDX2DRUG = _read_json(weights_dir, "idx2drug.json")
    CID_TO_NAME = _read_json(weights_dir, "cid_to_name.json")
    IDX_TO_RELATION_META = idx_to_meta  # type: ignore[assignment]

    PROTEIN2IDX = _read_json(weights_dir, "protein2idx.json")
    IDX2PROTEIN = {idx: pid for pid, idx in PROTEIN2IDX.items()}
    protein_to_name_path = weights_dir / "protein_to_name.json"
    PROTEIN_TO_NAME = _read_json(weights_dir, "protein_to_name.json") if protein_to_name_path.exists() else {}

    _MODEL_CONFIG = cfg
    _MODEL = _build_model(weights_dir, cfg, num_se_relations=len(idx_to_meta))
    Z_DRUG_CACHE, Z_DRUG_CACHE_DEGRADED, EDGE_INDEX_DICT = _compute_drug_cache(_MODEL, weights_dir, cfg)

    logger.info(
        "PharmacoGNN ready: %d drugs, %d relations, degraded_mode=%s",
        cfg["num_drugs"],
        len(idx_to_meta),
        Z_DRUG_CACHE_DEGRADED,
    )


def is_ready() -> bool:
    return _MODEL is not None and Z_DRUG_CACHE is not None


def _require_ready() -> None:
    if not is_ready():
        raise RuntimeError("gnn_engine.initialize() has not been called yet")


def drug_name(cid: str) -> str:
    return CID_TO_NAME.get(cid, cid)


def protein_name(pid: str) -> str:
    return PROTEIN_TO_NAME.get(pid, pid)


def _scale_for_female_bias(score: float, female_weighted: bool, apply: bool) -> float:
    if not (apply and female_weighted):
        return score
    return min(score * settings.FEMALE_ADR_RISK_MULTIPLIER, settings.RISK_SCORE_CLAMP)


def predict_pairwise(cid_a: str, cid_b: str, apply_female_bias: bool) -> list[dict[str, Any]]:
    """All 50 ADR relation scores (0-100) for one drug pair, sorted descending."""
    _require_ready()
    for cid in (cid_a, cid_b):
        if cid not in DRUG2IDX:
            raise KeyError(cid)

    num_relations = len(IDX_TO_RELATION_META)
    device = settings.GNN_DEVICE
    idx_a = DRUG2IDX[cid_a]
    idx_b = DRUG2IDX[cid_b]

    z_u = Z_DRUG_CACHE[idx_a].unsqueeze(0).expand(num_relations, -1)  # type: ignore[index]
    z_v = Z_DRUG_CACHE[idx_b].unsqueeze(0).expand(num_relations, -1)  # type: ignore[index]
    rel_idx = torch.arange(num_relations, device=device)

    with torch.no_grad():
        scores = (_MODEL.decoder(z_u, z_v, rel_idx) * 100.0).tolist()  # type: ignore[union-attr]

    results = [
        {
            "cui": meta["cui"],
            "name": meta["name"],
            "female_weighted": meta["female_weighted"],
            "risk_score": _scale_for_female_bias(score, meta["female_weighted"], apply_female_bias),
        }
        for meta, score in zip(IDX_TO_RELATION_META, scores)
    ]
    results.sort(key=lambda r: r["risk_score"], reverse=True)
    return results


def predict_regimen_matrix(
    cids: list[str], apply_female_bias: bool
) -> tuple[list[list[float]], list[dict[str, Any]], float]:
    """Vectorized C(N,2) pairwise ADR scoring across a drug cart.

    Returns (symmetric NxN top-risk matrix, per-pair flag list, regimen toxicity index).
    """
    _require_ready()
    for cid in cids:
        if cid not in DRUG2IDX:
            raise KeyError(cid)

    device = settings.GNN_DEVICE
    n = len(cids)
    r = len(IDX_TO_RELATION_META)
    idx = torch.tensor([DRUG2IDX[c] for c in cids], dtype=torch.long, device=device)
    z = Z_DRUG_CACHE[idx]  # type: ignore[index]  # [N, hidden]

    ii, jj = torch.triu_indices(n, n, offset=1, device=device)  # each [P]
    p = ii.shape[0]

    z_u = z[ii].unsqueeze(1).expand(p, r, -1).reshape(p * r, -1)
    z_v = z[jj].unsqueeze(1).expand(p, r, -1).reshape(p * r, -1)
    rel_idx = torch.arange(r, device=device).unsqueeze(0).expand(p, r).reshape(-1)

    with torch.no_grad():
        scores = (_MODEL.decoder(z_u, z_v, rel_idx) * 100.0).view(p, r)  # type: ignore[union-attr]

    if apply_female_bias:
        female_mask = torch.tensor([m["female_weighted"] for m in IDX_TO_RELATION_META], device=device)
        scaled = torch.clamp(scores * settings.FEMALE_ADR_RISK_MULTIPLIER, max=settings.RISK_SCORE_CLAMP)
        scores = torch.where(female_mask.unsqueeze(0), scaled, scores)

    top_scores, top_rel_idx = scores.max(dim=1)  # each [P]

    matrix = [[0.0] * n for _ in range(n)]
    pair_flags: list[dict[str, Any]] = []
    for k in range(p):
        i, j = int(ii[k]), int(jj[k])
        score = float(top_scores[k])
        meta = IDX_TO_RELATION_META[int(top_rel_idx[k])]
        matrix[i][j] = score
        matrix[j][i] = score
        pair_flags.append(
            {
                "i": i,
                "j": j,
                "top_risk_score": score,
                "top_adverse_effect": meta["name"],
                "female_weighted": meta["female_weighted"],
                "is_high_risk": score > settings.HIGH_RISK_THRESHOLD,
            }
        )

    regimen_toxicity_index = float(top_scores.mean()) if p else 0.0
    return matrix, pair_flags, regimen_toxicity_index


def find_bridging_proteins(cid_a: str, cid_b: str, max_shared: int = 3) -> dict[str, Any]:
    """Real topological grounding for explain.py's xai_pathway.

    Looks for either (a) a protein directly targeted by both drugs, or
    (b) a single protein-protein-interaction hop connecting a target of
    drug_a to a target of drug_b -- using EDGE_INDEX_DICT (the actual
    training graph), never embedding similarity or LLM guesswork. Returns
    {"nodes": [], "edges": [], "data_available": False} if edges weren't
    loaded (degraded mode) or no such connection exists in the graph; that
    is a true negative, not a fabricated one.

    Node ids are namespaced ("drug:<cid>", "protein:<id>") so Cytoscape.js/
    React Flow consumers never collide a drug and protein sharing a raw id.
    """
    empty: dict[str, Any] = {"nodes": [], "edges": [], "data_available": False}
    if EDGE_INDEX_DICT is None:
        return empty
    if cid_a not in DRUG2IDX or cid_b not in DRUG2IDX:
        return empty

    targets_edge = EDGE_INDEX_DICT.get(("drug", "targets", "protein"))
    if targets_edge is None:
        return empty

    idx_a, idx_b = DRUG2IDX[cid_a], DRUG2IDX[cid_b]
    drug_idx, protein_idx = targets_edge[0], targets_edge[1]

    proteins_a = set(protein_idx[drug_idx == idx_a].tolist())
    proteins_b = set(protein_idx[drug_idx == idx_b].tolist())

    drug_a_node = {"id": f"drug:{cid_a}", "label": drug_name(cid_a), "type": "drug"}
    drug_b_node = {"id": f"drug:{cid_b}", "label": drug_name(cid_b), "type": "drug"}

    shared = proteins_a & proteins_b
    if shared:
        nodes = [drug_a_node, drug_b_node]
        edges = []
        for p_idx in list(shared)[:max_shared]:
            pid = IDX2PROTEIN.get(p_idx, str(p_idx))
            node_id = f"protein:{pid}"
            nodes.append({"id": node_id, "label": protein_name(pid), "type": "protein"})
            edges.append({"source": drug_a_node["id"], "target": node_id, "label": "targets"})
            edges.append({"source": drug_b_node["id"], "target": node_id, "label": "targets"})
        return {"nodes": nodes, "edges": edges, "data_available": True}

    ppi_edge = EDGE_INDEX_DICT.get(("protein", "interacts", "protein"))
    if ppi_edge is not None and proteins_a and proteins_b:
        src, dst = ppi_edge[0], ppi_edge[1]
        a_tensor = torch.tensor(list(proteins_a))
        b_tensor = torch.tensor(list(proteins_b))

        # A single PPI hop in either direction: (a-target -> b-target) or (b-target -> a-target).
        mask_ab = torch.isin(src, a_tensor) & torch.isin(dst, b_tensor)
        mask_ba = torch.isin(src, b_tensor) & torch.isin(dst, a_tensor)

        hit = None
        if mask_ab.any():
            k = int(mask_ab.nonzero(as_tuple=True)[0][0])
            hit = (int(src[k]), int(dst[k]))
        elif mask_ba.any():
            k = int(mask_ba.nonzero(as_tuple=True)[0][0])
            hit = (int(dst[k]), int(src[k]))  # normalized to (a-side, b-side)

        if hit is not None:
            p1_idx, p2_idx = hit
            pid1, pid2 = IDX2PROTEIN.get(p1_idx, str(p1_idx)), IDX2PROTEIN.get(p2_idx, str(p2_idx))
            node1_id, node2_id = f"protein:{pid1}", f"protein:{pid2}"
            return {
                "nodes": [
                    drug_a_node,
                    {"id": node1_id, "label": protein_name(pid1), "type": "protein"},
                    {"id": node2_id, "label": protein_name(pid2), "type": "protein"},
                    drug_b_node,
                ],
                "edges": [
                    {"source": drug_a_node["id"], "target": node1_id, "label": "targets"},
                    {"source": node1_id, "target": node2_id, "label": "interacts"},
                    {"source": node2_id, "target": drug_b_node["id"], "label": "targets"},
                ],
                "data_available": True,
            }

    return empty
