from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.audit import AuditActionType, AuditLog
from app.models.patient import BiologicalSex, PatientCondition, PatientProfile
from app.models.user import User, UserRole
from app.schemas.predict import (
    ADRProbability,
    DrugDiseaseFlag,
    PairwiseFlag,
    PairwisePredictionRequest,
    PairwisePredictionResponse,
    RegimenPredictionRequest,
    RegimenPredictionResponse,
)
from app.services import gnn_engine

router = APIRouter(prefix="/predict", tags=["predict"])


async def _resolve_apply_female_bias(
    patient_id: UUID | None,
    patient_sex_override: BiologicalSex | None,
    current_user: User,
    db: AsyncSession,
    request: Request,
) -> bool:
    """Decide whether to apply the female-ADR risk multiplier, and audit any real PHI access.

    An explicit patient_sex override is a pure what-if simulation and never touches the DB.
    A patient_id triggers an RBAC check (a PATIENT may only query their own profile; a
    CLINICIAN may query any) and writes an AuditLog VIEW entry, since it resolves a real
    patient's stored demographic data.
    """
    if patient_sex_override is not None:
        return patient_sex_override == BiologicalSex.FEMALE

    if patient_id is None:
        return False

    if current_user.role == UserRole.PATIENT:
        own_profile_id = await db.scalar(
            select(PatientProfile.id).where(PatientProfile.user_id == current_user.id)
        )
        if own_profile_id != patient_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Patients may only query their own profile"
            )

    profile = await db.get(PatientProfile, patient_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")

    db.add(
        AuditLog(
            accessor_user_id=current_user.id,
            target_patient_id=profile.id,
            action_type=AuditActionType.VIEW,
            resource_type="PatientProfile",
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()

    return profile.biological_sex == BiologicalSex.FEMALE


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
    apply_female_bias = await _resolve_apply_female_bias(
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
    apply_female_bias = await _resolve_apply_female_bias(
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
