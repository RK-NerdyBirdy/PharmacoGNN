from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.models.patient import BiologicalSex


class ADRProbability(BaseModel):
    cui: str
    name: str
    female_weighted: bool
    risk_score: float = Field(description="0-100 risk score, after female-bias adjustment if applied")


class PairwisePredictionRequest(BaseModel):
    drug_a_cid: str
    drug_b_cid: str
    patient_id: UUID | None = Field(
        default=None, description="If set, loads biological_sex from this patient's profile (RBAC-checked, audited)"
    )
    patient_sex: BiologicalSex | None = Field(
        default=None, description="Explicit override; takes precedence over patient_id's stored value"
    )


class PairwisePredictionResponse(BaseModel):
    drug_a_cid: str
    drug_a_name: str
    drug_b_cid: str
    drug_b_name: str
    female_adjustment_applied: bool
    top_risk_score: float
    top_adverse_effect: str
    adverse_effects: list[ADRProbability]
    degraded_mode: bool = Field(
        description=(
            "True if Z_DRUG_CACHE was built from pre-convolution embeddings because no graph "
            "edge data was available at startup -- the 3-layer HGTConv encoder did not run. "
            "Scores are NOT from the fully trained, graph-contextualized model in this mode."
        )
    )


class RegimenPredictionRequest(BaseModel):
    drug_cids: list[str] = Field(min_length=2, description="PubChem CIDs of every drug in the cart")
    patient_id: UUID | None = None
    patient_sex: BiologicalSex | None = None


class PairwiseFlag(BaseModel):
    drug_a_cid: str
    drug_b_cid: str
    top_risk_score: float
    top_adverse_effect: str
    female_weighted: bool
    is_high_risk: bool


class DrugDiseaseFlag(BaseModel):
    drug_cid: str
    drug_name: str
    condition_name: str
    note: str


class RegimenPredictionResponse(BaseModel):
    drug_cids: list[str]
    drug_names: list[str]
    regimen_toxicity_index: float = Field(description="Mean of each pair's top ADR risk score, 0-100")
    interaction_matrix: list[list[float]] = Field(description="NxN symmetric matrix of pairwise top risk scores")
    pairwise_flags: list[PairwiseFlag]
    drug_disease_flags: list[DrugDiseaseFlag]
    degraded_mode: bool = Field(
        description="True if predictions were computed without running the HGTConv encoder (see gnn_engine)."
    )
