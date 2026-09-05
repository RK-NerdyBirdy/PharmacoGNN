from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.patient import PatientCondition
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
from app.services import drug_disease, gnn_engine, substitution
from app.services.patient_context import resolve_apply_female_bias

router = APIRouter(prefix="/predict", tags=["predict"])


async def _drug_disease_flags(
    patient_id: UUID | None, drug_cids: list[str], db: AsyncSession
) -> list[DrugDiseaseFlag]:
    """Cross-references the cart against the patient's active diagnosed conditions.

    Real, working query + cross-reference logic -- but see
    app/services/drug_disease.py: it returns [] until a curated,
    clinically-reviewed contraindication reference file is actually placed in
    backend/weights/. This function will never fabricate that content itself.
    """
    if patient_id is None:
        return []

    condition_names = (
        await db.scalars(
            select(PatientCondition.condition_name).where(
                PatientCondition.patient_id == patient_id, PatientCondition.is_active.is_(True)
            )
        )
    ).all()
    if not condition_names:
        return []

    raw_flags = drug_disease.screen(list(condition_names), drug_cids)
    return [
        DrugDiseaseFlag(
            drug_cid=flag["drug_cid"],
            drug_name=gnn_engine.drug_name(flag["drug_cid"]),
            condition_name=flag["condition_name"],
            note=flag["note"],
        )
        for flag in raw_flags
    ]


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
