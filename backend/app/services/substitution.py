from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F

from app.core.config import settings
from app.services import gnn_engine

# Entries whose canonical name is a training-time placeholder rather than a real,
# identified compound (see backend/weights/cid_to_name.json, e.g. "Unknown Drug
# (2022)") -- never surface these as a clinically viable substitute.
_DEPRECATED_NAME_MARKERS = ("Unknown Drug",)


def _is_deprecated(cid: str) -> bool:
    name = gnn_engine.CID_TO_NAME.get(cid, "")
    return any(marker in name for marker in _DEPRECATED_NAME_MARKERS)


def find_safe_substitutes(
    fixed_cid: str, target_cid: str, apply_female_bias: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """For a (fixed_cid, target_cid) pair, search safer alternatives to target_cid.

    Ranks candidates by embedding cosine similarity to target_cid (pharmacologically
    "closest" substitutes in Z_DRUG_CACHE), excludes deprecated/placeholder entries
    and the two original drugs, re-scores each candidate against fixed_cid with the
    real decoder, and returns the ones that actually reduce risk, sorted by steepest
    reduction. Only runs the (more expensive) candidate search at all when the
    original pair clears HIGH_RISK_THRESHOLD -- otherwise there's nothing to fix.

    Returns (original_pairwise_results, alternatives) where original_pairwise_results
    is gnn_engine.predict_pairwise's full 50-relation output for (fixed_cid, target_cid).
    """
    if not gnn_engine.is_ready():
        raise RuntimeError("gnn_engine.initialize() has not been called yet")
    if fixed_cid not in gnn_engine.DRUG2IDX:
        raise KeyError(fixed_cid)
    if target_cid not in gnn_engine.DRUG2IDX:
        raise KeyError(target_cid)

    original = gnn_engine.predict_pairwise(fixed_cid, target_cid, apply_female_bias)
    if original[0]["risk_score"] <= settings.HIGH_RISK_THRESHOLD:
        return original, []

    device = settings.GNN_DEVICE
    target_idx = gnn_engine.DRUG2IDX[target_cid]
    z_target = gnn_engine.Z_DRUG_CACHE[target_idx].unsqueeze(0)  # type: ignore[index]  # [1, hidden]
    similarities = F.cosine_similarity(z_target, gnn_engine.Z_DRUG_CACHE, dim=-1)  # type: ignore[arg-type]

    ranked_idx = torch.argsort(similarities, descending=True).tolist()

    candidate_cids: list[str] = []
    for idx in ranked_idx:
        cid = gnn_engine.IDX2DRUG[str(idx)]
        if cid in (target_cid, fixed_cid) or _is_deprecated(cid):
            continue
        candidate_cids.append(cid)
        if len(candidate_cids) >= settings.SUBSTITUTION_CANDIDATE_POOL_SIZE:
            break

    original_top_score = original[0]["risk_score"]
    scored: list[dict[str, Any]] = []
    for cid in candidate_cids:
        result = gnn_engine.predict_pairwise(fixed_cid, cid, apply_female_bias)
        top = result[0]
        scored.append(
            {
                "cid": cid,
                "name": gnn_engine.drug_name(cid),
                "similarity_to_original": float(similarities[gnn_engine.DRUG2IDX[cid]]),
                "new_top_risk_score": top["risk_score"],
                "new_top_adverse_effect": top["name"],
                "risk_reduction": original_top_score - top["risk_score"],
            }
        )

    viable = [c for c in scored if c["risk_reduction"] > 0]
    viable.sort(key=lambda c: c["risk_reduction"], reverse=True)
    return original, viable[: settings.SUBSTITUTION_TOP_N]
