from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.explain import SeverityClassification, XaiPathway
from app.schemas.predict import ADRProbability, SubstitutionCandidate

DISCLAIMER = "Not to be taken without clinical supervision."


class ReportAccepted(BaseModel):
    id: UUID
    status: str


class ModelStatus(BaseModel):
    degraded_mode: bool
    verified: bool = Field(
        default=False,
        description="Always false today -- the model's absolute risk scores have not been clinically validated.",
    )
    warning: str


class RegimenSnapshotItem(BaseModel):
    pubchem_cid: str
    drug_name: str
    dosage: str | None


class UnresolvedRegimenDrug(BaseModel):
    drug_name: str
    reason: str = Field(description='Almost always "not_in_vocabulary" -- see report_generation.py')


class ReportSummary(BaseModel):
    drug_count: int = Field(description="Count of active, resolvable drugs actually scored")
    high_risk_pair_count: int
    regimen_toxicity_index: float


class ReportPairwiseResult(BaseModel):
    drug_a_cid: str
    drug_b_cid: str
    top_risk_score: float
    top_adverse_effect: str
    is_high_risk: bool
    female_weighted: bool
    adverse_effects: list[ADRProbability]


class ReportSubstitution(BaseModel):
    for_drug_cid: str
    alternatives: list[SubstitutionCandidate]


class ReportExplanation(BaseModel):
    drug_a_cid: str
    drug_b_cid: str
    clinical_mechanism: str
    severity_classification: SeverityClassification
    patient_summary: str
    actionable_guidance: str
    xai_pathway: XaiPathway


class ReportRead(BaseModel):
    id: UUID
    patient_id: UUID
    status: str
    created_at: dt.datetime
    generated_by: UUID
    disclaimer: str = DISCLAIMER

    model_status: ModelStatus | None = None
    regimen_snapshot: list[RegimenSnapshotItem] = Field(default_factory=list)
    unresolved_drugs: list[UnresolvedRegimenDrug] = Field(default_factory=list)
    summary: ReportSummary | None = None
    interaction_matrix: list[list[float]] = Field(default_factory=list)
    pairwise: list[ReportPairwiseResult] = Field(default_factory=list)
    substitutions: list[ReportSubstitution] = Field(default_factory=list)
    explanations: list[ReportExplanation] = Field(default_factory=list)

    file_available: bool
    error_message: str | None = Field(
        default=None, description="Set only when status is failed"
    )


class ReportListItem(BaseModel):
    id: UUID
    status: str
    created_at: dt.datetime
    generated_by: UUID
    summary: ReportSummary | None = None
    file_available: bool
