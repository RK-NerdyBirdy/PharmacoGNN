from __future__ import annotations

import difflib
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import HGTConv

from app.core.config import settings

logger = logging.getLogger(__name__)

# The checkpoint (backend/weights/pharmacognn_deep_state_dict.pth) was reverse-
# engineered key-by-key: this exact class hierarchy loads it with
# `strict=True` and every key matching.
Metadata = tuple[list[str], list[tuple[str, str, str]]]

_GRAPH_EDGE_FILENAMES = ("graph_edge_index.pt", "hetero_graph.pt", "graph_edges.pt")

# Files that, if they change, mean index i in one artifact may no longer
# refer to the same drug/protein/relation as index i in another -- see the
# note on artifact fingerprinting below.
_VOCAB_FILENAMES_FOR_FINGERPRINT = (
    "model_config.json",
    "drug2idx.json",
    "protein2idx.json",
    "relation_meta.json",
)


class NodeEmbedding(nn.Module):
    """Learnable per-node-type input embeddings."""

    def __init__(self, num_drugs: int, num_proteins: int, dim: int) -> None:
        super().__init__()
        self.drug_emb = nn.Embedding(num_drugs, dim)
        self.protein_emb = nn.Embedding(num_proteins, dim)


class HGTResidualEncoder(nn.Module):
    """4-layer HGTConv stack with residual connections + LayerNorm + GELU."""

    def __init__(self, metadata: Metadata, hidden_dim: int, num_layers: int, heads: int, dropout: float = 0.3) -> None:
        super().__init__()
        node_types = metadata[0]
        self.dropout = dropout
        self.act = nn.GELU()

        self.convs = nn.ModuleList([
            HGTConv(hidden_dim, hidden_dim, metadata, heads=heads) for _ in range(num_layers)
        ])
        self.norms = nn.ModuleList([
            nn.ModuleDict({nt: nn.LayerNorm(hidden_dim) for nt in node_types}) for _ in range(num_layers)
        ])

    def forward(self, x_dict: dict[str, torch.Tensor], edge_index_dict: dict[tuple[str, str, str], torch.Tensor]) -> dict[str, torch.Tensor]:
        for conv, norm_dict in zip(self.convs, self.norms):
            out_dict = conv(x_dict, edge_index_dict)
            new_x_dict = {}
            for nt, x in x_dict.items():
                out = out_dict.get(nt)
                if out is None:
                    new_x_dict[nt] = x
                    continue
                out = self.act(out)
                out = F.dropout(out, p=self.dropout, training=self.training)
                h = x + out                      # Residual skip connection
                h = norm_dict[nt](h)             # per-node-type LayerNorm
                new_x_dict[nt] = h
            x_dict = new_x_dict
        return x_dict


class NeuralBilinearDecoder(nn.Module):
    """[z_u, z_v, z_u*z_v, |z_u-z_v|, e_r] -> MLP(256 -> 128 -> 1) -> sigmoid.

    The training notebook's decoder returns a raw logit (it's optimized via
    BCE-with-logits); this module folds the sigmoid into forward() instead of
    leaving it to the caller. That's a valid, equivalent refactor -- the
    learned nn.Linear/nn.Embedding weights loaded from the checkpoint are
    identical either way, and every caller in this file (predict_pairwise,
    predict_regimen_matrix) correctly treats this module's output as an
    already-bounded (0, 1) probability and does not re-apply sigmoid.
    """

    def __init__(self, hidden_dim: int, num_relations: int) -> None:
        super().__init__()
        self.rel_embed = nn.Embedding(num_relations, hidden_dim)
        input_dim = hidden_dim * 4 + hidden_dim

        self.mlp = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.LeakyReLU(0.2),
            nn.Linear(256, 128),
            nn.LeakyReLU(0.2),
            nn.Linear(128, 1),
        )

    def forward(self, z_u: torch.Tensor, z_v: torch.Tensor, rel_idx: torch.Tensor) -> torch.Tensor:
        e_r = self.rel_embed(rel_idx)
        feat = torch.cat([z_u, z_v, z_u * z_v, torch.abs(z_u - z_v), e_r], dim=-1)
        logits = self.mlp(feat).squeeze(-1)
        return torch.sigmoid(logits)


class PharmacoGNN(nn.Module):
    def __init__(
        self, num_drugs: int, num_proteins: int, hidden_dim: int, num_layers: int, heads: int, metadata: Metadata, num_se_relations: int, dropout: float = 0.3
    ) -> None:
        super().__init__()
        self.node_embed = NodeEmbedding(num_drugs, num_proteins, hidden_dim)
        self.encoder = HGTResidualEncoder(metadata, hidden_dim=hidden_dim, num_layers=num_layers, heads=heads, dropout=dropout)
        self.decoder = NeuralBilinearDecoder(hidden_dim, num_se_relations)


# --- Module-level inference state, populated once by initialize() -----------

_MODEL: PharmacoGNN | None = None
_MODEL_CONFIG: dict[str, Any] = {}

Z_DRUG_CACHE: torch.Tensor | None = None
Z_DRUG_CACHE_DEGRADED: bool = True

DRUG2IDX: dict[str, int] = {}
IDX2DRUG: dict[str, str] = {}
CID_TO_NAME: dict[str, str] = {}
IDX_TO_RELATION_META: list[dict[str, Any]] = []

PROTEIN2IDX: dict[str, int] = {}
IDX2PROTEIN: dict[int, str] = {}
PROTEIN_TO_NAME: dict[str, str] = {}
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
        dropout=cfg.get("dropout", 0.3)
    )

    weights_path = weights_dir / settings.MODEL_STATE_DICT_FILENAME
    if not weights_path.exists():
        raise RuntimeError(
            f"Model weights not found at {weights_path}. Refusing to serve predictions from "
            "randomly-initialized weights -- this is a clinical-safety system, not a demo."
        )

    state_dict = torch.load(weights_path, map_location=settings.GNN_DEVICE, weights_only=True)
    model.load_state_dict(state_dict, strict=True)
    model.to(settings.GNN_DEVICE)
    model.eval()
    return model


def _assert_vocab_consistency(
    model: PharmacoGNN, cfg: dict[str, Any], num_drug_ids: int, num_protein_ids: int, num_relation_ids: int
) -> None:
    """Catches gross artifact skew: a drug2idx.json / protein2idx.json /
    relation_meta.json that was NOT exported in the same notebook run as the
    currently-loaded state_dict. This cannot catch a same-COUNT reordering
    (e.g. index 42 quietly meaning a different drug) -- there is no content
    hash tying vocabulary order to a specific checkpoint. The real defense
    against that is exporting everything atomically in one notebook cell
    (see the training notebook's unified export step); this assertion is a
    second, independent line of defense for the mismatches it CAN detect,
    and it fails loudly rather than silently serving scrambled predictions.
    """
    checks = [
        ("num_drugs", cfg["num_drugs"], num_drug_ids, model.node_embed.drug_emb.weight.shape[0]),
        ("num_proteins", cfg["num_proteins"], num_protein_ids, model.node_embed.protein_emb.weight.shape[0]),
        ("num_relations", cfg["num_relations"], num_relation_ids, model.decoder.rel_embed.weight.shape[0]),
    ]
    problems = [
        f"{label}: model_config.json says {cfg_val}, vocab file has {file_val} entries, "
        f"trained embedding table has {emb_val} rows"
        for label, cfg_val, file_val, emb_val in checks
        if not (cfg_val == file_val == emb_val)
    ]
    if problems:
        raise RuntimeError(
            "PharmacoGNN artifact mismatch -- these files were not exported together from "
            "the same notebook run. Refusing to serve predictions that could be silently "
            "scrambled:\n  " + "\n  ".join(problems)
        )


def _try_load_edge_index_dict(
    weights_dir: Path,
) -> tuple[dict[tuple[str, str, str], torch.Tensor], str] | tuple[None, None]:
    for filename in _GRAPH_EDGE_FILENAMES:
        path = weights_dir / filename
        if not path.exists():
            continue
        obj = torch.load(path, map_location=settings.GNN_DEVICE, weights_only=False)
        edge_index_dict = getattr(obj, "edge_index_dict", obj) 
        if isinstance(edge_index_dict, dict):
            return edge_index_dict, filename
    return None, None


def _fingerprint(path: Path) -> dict[str, str | int]:
    hasher = hashlib.blake2b(digest_size=16)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return {"hash": hasher.hexdigest(), "size": path.stat().st_size}


def _source_fingerprint(weights_dir: Path, edge_filename: str | None) -> dict[str, Any]:
    """Fingerprints state_dict + edge file + every vocabulary/config file.

    The vocab files matter here as much as the state_dict: two exports can
    have byte-identical model_config.json shapes (same num_drugs/num_proteins
    counts) while drug2idx.json's actual ID->index mapping differs between
    them (e.g. one export re-ran the Decagon download and vocabulary build
    in a fresh session). That kind of skew changes nothing about tensor
    SHAPES -- load_state_dict still succeeds, nothing crashes -- but it
    silently misaligns which row of the embedding table is "drug 42" between
    the checkpoint and the ID mapping actually being used to serve requests.
    Hashing the vocab files too means ANY change to them invalidates the
    cache and forces a fresh encoder pass against whatever mapping is
    currently on disk, rather than serving a cache computed under a
    different (possibly now-stale) mapping.
    """
    weights_path = weights_dir / settings.MODEL_STATE_DICT_FILENAME
    fingerprint: dict[str, Any] = {
        "state_dict": _fingerprint(weights_path) if weights_path.exists() else None,
        "edge_filename": edge_filename,
        "vocab": {
            fname: _fingerprint(weights_dir / fname)
            for fname in _VOCAB_FILENAMES_FOR_FINGERPRINT
            if (weights_dir / fname).exists()
        },
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
            "state_dict/edge/vocab files -- source data changed, recomputing instead of "
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
    model: PharmacoGNN,
    weights_dir: Path,
    cfg: dict[str, Any],
    *,
    force_recompute: bool = False,
    skip_cache_write: bool = False,
) -> tuple[torch.Tensor, bool, dict[tuple[str, str, str], torch.Tensor] | None]:
    """
    force_recompute: if True, NEVER read Z_DRUG_CACHE.pt from disk even if its
        fingerprint matches -- always run the HGTConv encoder fresh. Use this
        when you want to be certain you're looking at output from the encoder
        + the *currently loaded* state_dict, not from whatever a previous
        process happened to leave on disk.
    skip_cache_write: if True, don't persist the freshly-computed embeddings
        back to Z_DRUG_CACHE.pt afterward. Combine with force_recompute=True
        for a pure one-off "run inference with zero cache involvement at all"
        pass that doesn't touch the cache file in either direction.
    """
    device = settings.GNN_DEVICE
    x_dict = {
        "drug": model.node_embed.drug_emb(torch.arange(cfg["num_drugs"], device=device)),
        "protein": model.node_embed.protein_emb(torch.arange(cfg["num_proteins"], device=device)),
    }

    edge_index_dict, edge_filename = _try_load_edge_index_dict(weights_dir)
    if edge_index_dict is None:
        logger.warning(
            "PharmacoGNN: no graph edge data found in %s (looked for %s). "
            "Z_DRUG_CACHE is falling back to PRE-CONVOLUTION drug embeddings.",
            weights_dir,
            _GRAPH_EDGE_FILENAMES,
        )
        return x_dict["drug"].clone(), True, None

    fingerprint = _source_fingerprint(weights_dir, edge_filename)

    if force_recompute:
        logger.warning(
            "PharmacoGNN: force_recompute=True -- ignoring any existing %s and running the "
            "HGTConv encoder over the full graph now.",
            settings.Z_DRUG_CACHE_FILENAME,
        )
    else:
        cached_z_drug = _load_cached_drug_cache(weights_dir, fingerprint)
        if cached_z_drug is not None:
            return cached_z_drug, False, edge_index_dict
        logger.warning(
            "PharmacoGNN: no valid %s found -- running the HGTConv encoder over the full graph now.",
            settings.Z_DRUG_CACHE_FILENAME,
        )

    z_dict = model.encoder(x_dict, edge_index_dict)
    z_drug = z_dict["drug"]

    if skip_cache_write:
        logger.info(
            "PharmacoGNN: skip_cache_write=True -- NOT persisting this recomputed %s to disk "
            "(this run is not affecting what future normal startups will load).",
            settings.Z_DRUG_CACHE_FILENAME,
        )
    else:
        _save_drug_cache(weights_dir, z_drug, fingerprint)

    return z_drug, False, edge_index_dict


def initialize(*, force_recompute: bool = False, skip_cache_write: bool = False) -> None:
    """
    force_recompute / skip_cache_write: passed straight through to
    _compute_drug_cache -- see its docstring. Both default to False, i.e.
    unchanged behavior from before (read the cache if valid, write a fresh
    one if not).
    """
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

    # Fail loudly here rather than downstream as an unexplained "predictions
    # look wrong" support ticket -- see _assert_vocab_consistency's docstring.
    _assert_vocab_consistency(_MODEL, cfg, len(DRUG2IDX), len(PROTEIN2IDX), len(idx_to_meta))

    Z_DRUG_CACHE, Z_DRUG_CACHE_DEGRADED, EDGE_INDEX_DICT = _compute_drug_cache(
        _MODEL, weights_dir, cfg, force_recompute=force_recompute, skip_cache_write=skip_cache_write
    )

    logger.info(
        "PharmacoGNN ready: %d drugs, %d relations, degraded_mode=%s",
        cfg["num_drugs"],
        len(idx_to_meta),
        Z_DRUG_CACHE_DEGRADED,
    )
    if Z_DRUG_CACHE_DEGRADED:
        logger.warning(
            "PharmacoGNN: running in DEGRADED mode -- Z_DRUG_CACHE holds raw, "
            "pre-message-passing embeddings (no graph_edge_index.pt found). "
            "Predictions will be materially weaker than the trained model is "
            "actually capable of. This is not a crash-worthy condition by "
            "design (so the API stays up), but it should not be treated as "
            "normal in any environment serving real predictions."
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


def vocab_sample(n: int = 15) -> list[dict[str, Any]]:
    """Debug helper: the first n (cid, idx, resolved-name) entries, exactly as
    they currently sit in DRUG2IDX / CID_TO_NAME. Print this when a name-based
    lookup unexpectedly finds nothing -- it tells you in one glance whether
    CID_TO_NAME actually holds common drug names, technical/IUPAC names, or
    just the CID echoed back because a name lookup failed at export time.
    """
    _require_ready()
    return [
        {"cid": cid, "idx": idx, "name": CID_TO_NAME.get(cid, "<MISSING FROM CID_TO_NAME>")}
        for cid, idx in list(DRUG2IDX.items())[:n]
    ]


def find_drug(query: str, limit: int = 5) -> list[tuple[str, str]]:
    """Debug/lookup helper, more forgiving than a bare substring check:
      1. If `query` is itself a valid CID key, returns it directly.
      2. Case-insensitive substring match against CID_TO_NAME's values.
      3. If that finds nothing, falls back to difflib fuzzy matching so a
         near-miss (e.g. an IUPAC/chemical name instead of the trade name)
         still surfaces as a suggestion instead of silently returning empty.
    Returns a list of (cid, name) pairs, most-likely match first where
    fuzzy matching was used.
    """
    _require_ready()
    if query in DRUG2IDX:
        return [(query, CID_TO_NAME.get(query, query))]

    q = query.lower()
    substr_hits = [(cid, name) for cid, name in CID_TO_NAME.items() if q in name.lower()]
    if substr_hits:
        return substr_hits[:limit]

    names = list(CID_TO_NAME.values())
    close_names = difflib.get_close_matches(query, names, n=limit, cutoff=0.4)
    name_to_cid: dict[str, str] = {}
    for cid, name in CID_TO_NAME.items():
        name_to_cid.setdefault(name, cid)
    return [(name_to_cid[name], name) for name in close_names]


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
    """Vectorized C(N,2) pairwise ADR scoring across a drug cart."""
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
    """Real topological grounding for explain.py's xai_pathway."""
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
        # NOTE: these two tensors previously had no `device=` argument, which
        # would raise a device-mismatch RuntimeError against `src`/`dst`
        # (loaded onto settings.GNN_DEVICE) any time this ran on a GPU
        # deployment. Fixed by pinning them to src's device explicitly.
        a_tensor = torch.tensor(list(proteins_a), device=src.device)
        b_tensor = torch.tensor(list(proteins_b), device=src.device)

        mask_ab = torch.isin(src, a_tensor) & torch.isin(dst, b_tensor)
        mask_ba = torch.isin(src, b_tensor) & torch.isin(dst, a_tensor)

        hit = None
        if mask_ab.any():
            k = int(mask_ab.nonzero(as_tuple=True)[0][0])
            hit = (int(src[k]), int(dst[k]))
        elif mask_ba.any():
            k = int(mask_ba.nonzero(as_tuple=True)[0][0])
            hit = (int(dst[k]), int(src[k])) 

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