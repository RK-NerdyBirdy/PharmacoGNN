from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.patient import BiologicalSex


class PatientProfileCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=255)
    date_of_birth: dt.date
    medical_record_number: str = Field(min_length=1, max_length=255)
    emergency_contact: str | None = None
    biological_sex: BiologicalSex
    age: int = Field(ge=0, le=130)


class PatientProfileCreateForUser(PatientProfileCreate):
    user_id: UUID = Field(description="The PATIENT-role user this profile belongs to")


class PatientProfileUpdate(BaseModel):
    legal_name: str | None = Field(default=None, min_length=1, max_length=255)
    date_of_birth: dt.date | None = None
    medical_record_number: str | None = Field(default=None, min_length=1, max_length=255)
    emergency_contact: str | None = None
    biological_sex: BiologicalSex | None = None
    age: int | None = Field(default=None, ge=0, le=130)


class PatientProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    legal_name: str
    date_of_birth: dt.date
    medical_record_number: str
    emergency_contact: str | None
    biological_sex: BiologicalSex
    age: int


class PatientConditionCreate(BaseModel):
    condition_name: str = Field(min_length=1, max_length=255)
    icd10_code: str | None = Field(default=None, max_length=16)
    diagnosed_date: dt.date | None = None


class PatientConditionUpdate(BaseModel):
    is_active: bool | None = None
    diagnosed_date: dt.date | None = None
    icd10_code: str | None = Field(default=None, max_length=16)


class PatientConditionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    condition_name: str
    icd10_code: str | None
    diagnosed_date: dt.date | None
    is_active: bool


class PatientRegimenCreate(BaseModel):
    pubchem_cid: int
    drug_name: str = Field(min_length=1, max_length=255)
    dosage: str | None = Field(default=None, max_length=128)
    start_date: dt.date


class PatientRegimenUpdate(BaseModel):
    dosage: str | None = Field(default=None, max_length=128)
    end_date: dt.date | None = Field(default=None, description="Set to discontinue the medication")


class PatientRegimenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    pubchem_cid: int
    drug_name: str
    dosage: str | None
    start_date: dt.date
    end_date: dt.date | None
    prescriber_id: UUID | None
