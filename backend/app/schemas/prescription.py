from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from app.schemas.patient import PatientRegimenRead


class PrescriptionItemCreate(BaseModel):
    drug_name: str = Field(min_length=1, max_length=255)
    pubchem_cid: str | None = Field(
        default=None, max_length=20, description="If known; otherwise resolved from drug_name"
    )
    dosage: str | None = Field(default=None, max_length=128)
    frequency: str | None = Field(default=None, max_length=64)
    route: str | None = Field(default=None, max_length=32)
    start_date: dt.date
    end_date: dt.date | None = None
    instructions: str | None = Field(default=None, max_length=500)


class PrescriptionCreate(BaseModel):
    prescriber_name: str | None = Field(
        default=None, max_length=255, description="Who actually wrote this prescription, if not a system user"
    )
    issued_date: dt.date | None = None
    allow_partial: bool = Field(
        default=False,
        description=(
            "False (default): if ANY item fails to resolve, nothing is committed. "
            "True: resolvable items are created; unresolved ones are reported and skipped."
        ),
    )
    items: list[PrescriptionItemCreate] = Field(min_length=1, max_length=50)


class UnresolvedPrescriptionItem(BaseModel):
    drug_name: str
    pubchem_cid: str | None
    reason: str = Field(
        description="not_in_vocabulary | cid_not_in_vocabulary | ambiguous_name | missing_identifier"
    )


class PrescriptionImportResponse(BaseModel):
    created: list[PatientRegimenRead]
    unresolved: list[UnresolvedPrescriptionItem]
    committed: bool = Field(description="Whether anything was actually written to the database")
