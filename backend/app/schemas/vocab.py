from __future__ import annotations

from pydantic import BaseModel


class DrugVocabEntry(BaseModel):
    cid: str
    name: str


class AdverseEffectVocabEntry(BaseModel):
    cui: str
    name: str
    female_weighted: bool
