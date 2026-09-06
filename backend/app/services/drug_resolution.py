"""Resolving a prescription line item to a canonical, in-vocabulary drug.

The model only knows 645 PubChem CIDs (gnn_engine.DRUG2IDX). Anything a
prescription mentions that isn't one of them cannot be scored, substituted,
or explained -- and if it's silently dropped from a regimen, every downstream
interaction report looks safer than the patient's actual regimen really is.
So resolution failures are a first-class result here, never an exception
swallowed into "just leave it out."

Matching is deliberately conservative: exact, case-insensitive name match
only. No fuzzy/substring matching. Guessing that "Asprin" means "Aspirin" is
exactly the kind of silent correction that's fine in a search box and
dangerous in a clinical record -- a wrong guess here writes the wrong drug
into a patient's regimen. An honest "not found" is always safer than a
plausible-looking wrong answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services import gnn_engine


@dataclass
class DrugResolution:
    resolved: bool
    cid: str | None = None
    name: str | None = None
    reason: str | None = None  # set iff not resolved


def resolve_drug(drug_name: str | None, pubchem_cid: str | None) -> DrugResolution:
    """An explicit pubchem_cid is authoritative; drug_name is used only when it's absent."""
    if pubchem_cid:
        normalized = pubchem_cid.strip().upper()
        if normalized in gnn_engine.DRUG2IDX:
            return DrugResolution(resolved=True, cid=normalized, name=gnn_engine.drug_name(normalized))
        return DrugResolution(resolved=False, reason="cid_not_in_vocabulary")

    if not drug_name or not drug_name.strip():
        return DrugResolution(resolved=False, reason="missing_identifier")

    needle = drug_name.strip().lower()
    matches = [cid for cid, name in gnn_engine.CID_TO_NAME.items() if name.lower() == needle]

    if len(matches) == 1:
        cid = matches[0]
        return DrugResolution(resolved=True, cid=cid, name=gnn_engine.drug_name(cid))
    if len(matches) > 1:
        return DrugResolution(resolved=False, reason="ambiguous_name")
    return DrugResolution(resolved=False, reason="not_in_vocabulary")
