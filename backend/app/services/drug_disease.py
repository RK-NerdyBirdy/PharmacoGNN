"""Drug-disease contraindication screening.

This module is real, working infrastructure with intentionally no built-in
clinical content. Inventing contraindication rules (e.g. "flag anything with
'QT' in the condition name against a hardcoded drug list") would mean
fabricating clinical guidance inside a decision-support system, which this
codebase will not do. Once someone supplies a real, reviewed reference file
in the format below, this starts working with zero code changes.

Expected file: WEIGHTS_DIR / settings.DRUG_DISEASE_REFERENCE_FILENAME
(default "drug_disease_contraindications.json"), shaped as:

    {
      "<condition name, matched case-insensitively against PatientCondition.condition_name>": [
        {"drug_cid": "CID000000085", "note": "why this combination is flagged"}
      ]
    }

Keys are matched by exact (case-insensitive) condition name -- there is no
fuzzy/synonym matching, so the reference file's keys must match however
conditions are actually recorded via POST /patients/{id}/conditions.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import settings

_reference_cache: dict[str, list[dict[str, str]]] | None = None


def _load_reference() -> dict[str, list[dict[str, str]]]:
    global _reference_cache
    if _reference_cache is not None:
        return _reference_cache

    path = settings.WEIGHTS_DIR / settings.DRUG_DISEASE_REFERENCE_FILENAME
    if not path.exists():
        _reference_cache = {}
        return _reference_cache

    _reference_cache = json.loads(path.read_text(encoding="utf-8"))
    return _reference_cache


def reset_cache() -> None:
    """For tests, or after hot-swapping the reference file without a restart."""
    global _reference_cache
    _reference_cache = None


def screen(condition_names: list[str], drug_cids: list[str]) -> list[dict[str, Any]]:
    """Cross-references a patient's active conditions against a drug cart.

    Returns [] whenever the reference file is absent (the current, honest
    default) -- never a guessed result.
    """
    reference = _load_reference()
    if not reference or not condition_names:
        return []

    condition_by_lower = {c.lower(): c for c in condition_names}
    drug_cid_set = set(drug_cids)

    flags: list[dict[str, Any]] = []
    for condition_key, entries in reference.items():
        matched_condition = condition_by_lower.get(condition_key.lower())
        if matched_condition is None:
            continue
        for entry in entries:
            if entry.get("drug_cid") in drug_cid_set:
                flags.append(
                    {
                        "drug_cid": entry["drug_cid"],
                        "condition_name": matched_condition,
                        "note": entry.get("note", ""),
                    }
                )
    return flags
