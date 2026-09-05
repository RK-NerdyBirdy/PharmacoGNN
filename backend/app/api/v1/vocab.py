from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.vocab import AdverseEffectVocabEntry, DrugVocabEntry
from app.services import gnn_engine

router = APIRouter(prefix="/vocab", tags=["vocab"])

# Read-only reference data (drug/CID names, the 50 ADR relations) for search/
# autocomplete UI. Requires auth like everything else, but isn't RBAC-scoped
# by role -- it's non-PHI vocabulary, not a specific patient's data.


@router.get("/drugs", response_model=list[DrugVocabEntry])
async def search_drugs(
    current_user: Annotated[User, Depends(get_current_user)],
    q: Annotated[str, Query(description="Case-insensitive substring match against drug name")] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DrugVocabEntry]:
    q_lower = q.lower()
    matches = [
        DrugVocabEntry(cid=cid, name=gnn_engine.drug_name(cid))
        for cid in gnn_engine.DRUG2IDX
        if q_lower in gnn_engine.drug_name(cid).lower()
    ]
    return matches[offset : offset + limit]


@router.get("/drugs/{cid}", response_model=DrugVocabEntry)
async def get_drug(cid: str, current_user: Annotated[User, Depends(get_current_user)]) -> DrugVocabEntry:
    if cid not in gnn_engine.DRUG2IDX:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown drug CID")
    return DrugVocabEntry(cid=cid, name=gnn_engine.drug_name(cid))


@router.get("/adverse-effects", response_model=list[AdverseEffectVocabEntry])
async def list_adverse_effects(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[AdverseEffectVocabEntry]:
    # Only 50 relations total -- returned in full, no pagination needed.
    return [
        AdverseEffectVocabEntry(cui=meta["cui"], name=meta["name"], female_weighted=meta["female_weighted"])
        for meta in gnn_engine.IDX_TO_RELATION_META
    ]


@router.get("/adverse-effects/{cui}", response_model=AdverseEffectVocabEntry)
async def get_adverse_effect(
    cui: str, current_user: Annotated[User, Depends(get_current_user)]
) -> AdverseEffectVocabEntry:
    for meta in gnn_engine.IDX_TO_RELATION_META:
        if meta["cui"] == cui:
            return AdverseEffectVocabEntry(cui=meta["cui"], name=meta["name"], female_weighted=meta["female_weighted"])
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown adverse_effect_cui")
