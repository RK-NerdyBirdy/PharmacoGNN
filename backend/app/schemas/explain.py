from __future__ import annotations

import enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.patient import BiologicalSex


class SeverityClassification(str, enum.Enum):
    CONTRAINDICATED = "Contraindicated"
    MAJOR = "Major"
    MODERATE = "Moderate"
    MINOR = "Minor"


class ExplainInteractionRequest(BaseModel):
    drug_a_cid: str
    drug_b_cid: str
    adverse_effect_cui: str | None = Field(
        default=None, description="Which of the 50 ADR relations to explain; defaults to the top-scoring one"
    )
    patient_id: UUID | None = None
    patient_sex: BiologicalSex | None = None


class XaiPathwayNode(BaseModel):
    id: str
    label: str
    type: str = Field(description='"drug" or "protein"')


class XaiPathwayEdge(BaseModel):
    source: str
    target: str
    label: str


class XaiPathway(BaseModel):
    nodes: list[XaiPathwayNode] = Field(default_factory=list)
    edges: list[XaiPathwayEdge] = Field(default_factory=list)
    data_available: bool = Field(
        description=(
            "False when no real graph topology was available to ground this pathway -- nodes/edges "
            "are then empty by construction, never LLM-invented, since backend/weights currently has "
            "no drug-protein/protein-protein edge data (see gnn_engine.Z_DRUG_CACHE_DEGRADED)."
        )
    )


class InteractionExplanation(BaseModel):
    clinical_mechanism: str
    severity_classification: SeverityClassification
    patient_summary: str
    actionable_guidance: str
    xai_pathway: XaiPathway


class ExplainInteractionResponse(BaseModel):
    drug_a_cid: str
    drug_a_name: str
    drug_b_cid: str
    drug_b_name: str
    adverse_effect: str
    risk_score: float
    female_adjustment_applied: bool
    explanation: InteractionExplanation
    degraded_mode: bool = Field(
        description="True if the GNN risk_score above came from the pre-convolution embedding fallback."
    )
