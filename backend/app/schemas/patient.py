from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.patient import BiologicalSex


class PatientProfileCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=255)
    date_of_birth: dt.date
    medical_record_number: str = Field(min_length=1, max_length=255)
    emergency_contact: str | None = None
    biological_sex: BiologicalSex
    age: int = Field(ge=0, le=130)


class PatientOnboard(PatientProfileCreate):
    """Clinician-driven onboarding: creates the login account too.

    Takes an email rather than a user_id because patients have no way to
    self-register -- the account, the profile, the assignment and the invite
    are all created by this one call.
    """

    email: EmailStr


class PatientProfileUpdate(BaseModel):
    # Same reasoning as PatientSelfUpdate: on a PATCH, silently ignoring a
    # misspelled or unsupported field is worse than a 422.
    model_config = ConfigDict(extra="forbid")

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


class PatientSelfUpdate(BaseModel):
    """The only fields a PATIENT may change on their own record.

    Deliberately excludes date_of_birth, medical_record_number and
    biological_sex: those are clinical identifiers, and biological_sex in
    particular feeds the model's risk stratification, so a patient editing it
    would silently change their own risk scores. Email lives on User and
    changes through a separate verify-the-new-address flow, not here.

    extra="forbid" matters here: Pydantic's default is to *drop* unknown
    fields, which would make an attempt to set biological_sex return 200 with
    the field quietly ignored -- safe, but it tells the client the edit
    succeeded when it didn't. Rejecting outright is the honest answer.
    """

    model_config = ConfigDict(extra="forbid")

    legal_name: str | None = Field(default=None, min_length=1, max_length=255)
    age: int | None = Field(default=None, ge=0, le=130)
    emergency_contact: str | None = None


class PatientOnboardResponse(PatientProfileRead):
    activation_status: str = Field(description='"pending" until the patient sets a password, then "active"')
    invite_email_status: str = Field(
        description='"sent" or "failed" -- a failure does NOT mean the patient wasn\'t created'
    )


class PatientListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    legal_name: str
    age: int
    biological_sex: BiologicalSex
    is_primary: bool = Field(description="Whether the requesting clinician is this patient's primary")
    assigned_at: dt.datetime
    active_regimen_count: int
    activation_status: str


class PatientAccessEntry(BaseModel):
    """One clinician who currently holds access to a patient."""

    clinician_id: UUID
    clinician_email: str
    is_primary: bool
    assigned_at: dt.datetime


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
    """drug_name is always required; pubchem_cid is an optional shortcut.

    If pubchem_cid is given it's authoritative and must be a real,
    in-vocabulary CID (validated by services/drug_resolution.py, not by this
    schema) -- if it isn't, or if it's omitted and drug_name doesn't match
    anything, the endpoint returns 422 rather than storing an unresolvable
    drug.
    """

    pubchem_cid: str | None = Field(default=None, max_length=20)
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
    pubchem_cid: str
    drug_name: str
    dosage: str | None
    start_date: dt.date
    end_date: dt.date | None
    prescriber_id: UUID | None
    external_prescriber_name: str | None
    import_batch_id: UUID | None
