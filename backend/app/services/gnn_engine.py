from __future__ import annotations

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

_GRAPH_EDGE_FILENAMES = ("hetero_graph.pt", "graph_edges.pt")


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
    parameter-free, so the *inter-layer activation* below (ReLU after each
    LayerNorm) could not be verified the same way -- it's the standard choice
    for stacked HGTConv encoders, not a confirmed fact about this checkpoint.
    Revisit if the original training script surfaces and says otherwise.
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


def _try_load_edge_index_dict(weights_dir: Path) -> dict[tuple[str, str, str], torch.Tensor] | None:
    """Looks for graph edges produced by the training pipeline.

    Not part of the artifacts shipped in backend/weights/ as of this writing --
    only ID vocabularies and the trained state_dict are present. Returns None
    (rather than fabricating topology) if nothing is found; callers must treat
    that as a real, visible degraded mode, not a silent fallback.
    """
    for filename in _GRAPH_EDGE_FILENAMES:
        path = weights_dir / filename
        if not path.exists():
            continue
        obj = torch.load(path, map_location=settings.GNN_DEVICE, weights_only=False)
        edge_index_dict = getattr(obj, "edge_index_dict", obj)  # HeteroData, or an already-plain dict
        if isinstance(edge_index_dict, dict):
            return edge_index_dict
    return None


@torch.no_grad()
def _compute_drug_cache(model: PharmacoGNN, weights_dir: Path, cfg: dict[str, Any]) -> tuple[torch.Tensor, bool]:
    device = settings.GNN_DEVICE
    x_dict = {
        "drug": model.node_embed.drug_emb(torch.arange(cfg["num_drugs"], device=device)),
        "protein": model.node_embed.protein_emb(torch.arange(cfg["num_proteins"], device=device)),
    }

    edge_index_dict = _try_load_edge_index_dict(weights_dir)
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
        return x_dict["drug"].clone(), True

    z_dict = model.encoder(x_dict, edge_index_dict)
    return z_dict["drug"], False


def initialize() -> None:
    """Load artifacts + weights and populate Z_DRUG_CACHE. Call once at app startup."""
    global _MODEL, _MODEL_CONFIG, Z_DRUG_CACHE, Z_DRUG_CACHE_DEGRADED
    global DRUG2IDX, IDX2DRUG, CID_TO_NAME, IDX_TO_RELATION_META

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

    _MODEL_CONFIG = cfg
    _MODEL = _build_model(weights_dir, cfg, num_se_relations=len(idx_to_meta))
    Z_DRUG_CACHE, Z_DRUG_CACHE_DEGRADED = _compute_drug_cache(_MODEL, weights_dir, cfg)

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
