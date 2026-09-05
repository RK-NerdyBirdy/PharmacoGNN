from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.user import User
from app.schemas.predict import (
    ADRProbability,
    DrugDiseaseFlag,
    PairwiseFlag,
    PairwisePredictionRequest,
    PairwisePredictionResponse,
    RegimenPredictionRequest,
    RegimenPredictionResponse,
    SubstitutionCandidate,
    SubstitutionRequest,
    SubstitutionResponse,
)
from app.services import gnn_engine, substitution
from app.services.patient_context import resolve_apply_female_bias

router = APIRouter(prefix="/predict", tags=["predict"])


async def _drug_disease_flags(
    patient_id: UUID | None, drug_cids: list[str], db: AsyncSession
) -> list[DrugDiseaseFlag]:
    """Cross-reference the cart against the patient's diagnosed conditions.

    NOT IMPLEMENTED YET: doing this responsibly requires a curated drug-disease
    contraindication reference (e.g. condition -> contraindicated drug/drug-class
    mapping sourced from DrugBank/FDA labeling), which does not exist in
    backend/weights/ -- those artifacts are the ADR *interaction* graph's
    vocabularies, not a disease-contraindication table. Fabricating heuristic
    rules here (e.g. name-matching "QT" conditions against a hardcoded drug
    list) would mean inventing clinical guidance, which this endpoint will not
    do. Once a real reference dataset is available, this should query
    PatientCondition for `patient_id` and cross-reference it against that table.
    """
    return []


@router.post("/pairwise", response_model=PairwisePredictionResponse)
async def predict_pairwise(
    payload: PairwisePredictionRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PairwisePredictionResponse:
    apply_female_bias = await resolve_apply_female_bias(
        payload.patient_id, payload.patient_sex, current_user, db, request
    )

    try:
        adverse_effects = gnn_engine.predict_pairwise(payload.drug_a_cid, payload.drug_b_cid, apply_female_bias)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown drug CID: {exc.args[0]}"
        ) from exc

    top = adverse_effects[0]
    return PairwisePredictionResponse(
        drug_a_cid=payload.drug_a_cid,
        drug_a_name=gnn_engine.drug_name(payload.drug_a_cid),
        drug_b_cid=payload.drug_b_cid,
        drug_b_name=gnn_engine.drug_name(payload.drug_b_cid),
        female_adjustment_applied=apply_female_bias,
        top_risk_score=top["risk_score"],
        top_adverse_effect=top["name"],
        adverse_effects=[ADRProbability(**effect) for effect in adverse_effects],
        degraded_mode=gnn_engine.Z_DRUG_CACHE_DEGRADED,
    )


@router.post("/regimen", response_model=RegimenPredictionResponse)
async def predict_regimen(
    payload: RegimenPredictionRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RegimenPredictionResponse:
    apply_female_bias = await resolve_apply_female_bias(
        payload.patient_id, payload.patient_sex, current_user, db, request
    )

    try:
        matrix, pair_flags, toxicity_index = gnn_engine.predict_regimen_matrix(payload.drug_cids, apply_female_bias)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown drug CID: {exc.args[0]}"
        ) from exc

    drug_disease_flags = await _drug_disease_flags(payload.patient_id, payload.drug_cids, db)

    return RegimenPredictionResponse(
        drug_cids=payload.drug_cids,
        drug_names=[gnn_engine.drug_name(cid) for cid in payload.drug_cids],
        regimen_toxicity_index=toxicity_index,
        interaction_matrix=matrix,
        pairwise_flags=[
            PairwiseFlag(
                drug_a_cid=payload.drug_cids[flag["i"]],
                drug_b_cid=payload.drug_cids[flag["j"]],
                top_risk_score=flag["top_risk_score"],
                top_adverse_effect=flag["top_adverse_effect"],
                female_weighted=flag["female_weighted"],
                is_high_risk=flag["is_high_risk"],
            )
            for flag in pair_flags
        ],
        drug_disease_flags=drug_disease_flags,
        degraded_mode=gnn_engine.Z_DRUG_CACHE_DEGRADED,
    )


@router.post("/substitute", response_model=SubstitutionResponse)
async def substitute_drug(
    payload: SubstitutionRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubstitutionResponse:
    apply_female_bias = await resolve_apply_female_bias(
        payload.patient_id, payload.patient_sex, current_user, db, request
    )

    try:
        original, alternatives = substitution.find_safe_substitutes(
            payload.drug_a_cid, payload.drug_b_cid, apply_female_bias
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown drug CID: {exc.args[0]}"
        ) from exc

    top = original[0]
    return SubstitutionResponse(
        drug_a_cid=payload.drug_a_cid,
        drug_a_name=gnn_engine.drug_name(payload.drug_a_cid),
        drug_b_cid=payload.drug_b_cid,
        drug_b_name=gnn_engine.drug_name(payload.drug_b_cid),
        original_top_risk_score=top["risk_score"],
        original_top_adverse_effect=top["name"],
        substitution_recommended=top["risk_score"] > settings.HIGH_RISK_THRESHOLD,
        alternatives=[SubstitutionCandidate(**candidate) for candidate in alternatives],
        degraded_mode=gnn_engine.Z_DRUG_CACHE_DEGRADED,
    )
