from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.explain import (
    ExplainInteractionRequest,
    ExplainInteractionResponse,
    XaiPathway,
    XaiPathwayEdge,
    XaiPathwayNode,
)
from app.services import gnn_engine, llm_explainer
from app.services.patient_context import resolve_apply_female_bias

router = APIRouter(prefix="/explain", tags=["explain"])


@router.post("/interaction", response_model=ExplainInteractionResponse)
async def explain_interaction(
    payload: ExplainInteractionRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExplainInteractionResponse:
    apply_female_bias = await resolve_apply_female_bias(
        payload.patient_id, payload.patient_sex, current_user, db, request
    )

    try:
        results = gnn_engine.predict_pairwise(payload.drug_a_cid, payload.drug_b_cid, apply_female_bias)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown drug CID: {exc.args[0]}"
        ) from exc

    if payload.adverse_effect_cui is not None:
        target = next((r for r in results if r["cui"] == payload.adverse_effect_cui), None)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown adverse_effect_cui")
    else:
        target = results[0]

    drug_a_name = gnn_engine.drug_name(payload.drug_a_cid)
    drug_b_name = gnn_engine.drug_name(payload.drug_b_cid)
    female_adjustment_applied = apply_female_bias and target["female_weighted"]

    # Real graph lookup (shared drug target, or a single protein-protein-interaction
    # hop) -- never LLM-invented. Empty/data_available=False if edges aren't loaded
    # or no such connection exists.
    pathway = gnn_engine.find_bridging_proteins(payload.drug_a_cid, payload.drug_b_cid)

    context = {
        "drug_a_cid": payload.drug_a_cid,
        "drug_a_name": drug_a_name,
        "drug_b_cid": payload.drug_b_cid,
        "drug_b_name": drug_b_name,
        "adverse_effect": target["name"],
        "risk_score": target["risk_score"],
        "female_adjustment_applied": female_adjustment_applied,
        "pathway": {"nodes": pathway["nodes"], "edges": pathway["edges"]},
    }

    try:
        explanation = await llm_explainer.explain_interaction(context)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    # The LLM's own xai_pathway attempt is discarded in favor of the graph lookup
    # above: transcription by an LLM (even instructed not to invent nodes) is a
    # weaker guarantee than using the query result directly for a field that's
    # meant to be an exact, inspectable graph payload.
    explanation.xai_pathway = XaiPathway(
        nodes=[XaiPathwayNode(**n) for n in pathway["nodes"]],
        edges=[XaiPathwayEdge(**e) for e in pathway["edges"]],
        data_available=pathway["data_available"],
    )

    return ExplainInteractionResponse(
        drug_a_cid=payload.drug_a_cid,
        drug_a_name=drug_a_name,
        drug_b_cid=payload.drug_b_cid,
        drug_b_name=drug_b_name,
        adverse_effect=target["name"],
        risk_score=target["risk_score"],
        female_adjustment_applied=female_adjustment_applied,
        explanation=explanation,
        degraded_mode=gnn_engine.Z_DRUG_CACHE_DEGRADED,
    )
