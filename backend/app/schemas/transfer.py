from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class ClinicianRef(BaseModel):
    id: UUID
    email: str


class TransferCreate(BaseModel):
    to_clinician_email: EmailStr


class TransferConsent(BaseModel):
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TransferRead(BaseModel):
    id: UUID
    patient_id: UUID
    from_clinician: ClinicianRef
    to_clinician: ClinicianRef
    status: str
    otp_expires_at: dt.datetime
    attempts_remaining: int
    created_at: dt.datetime
    consented_at: dt.datetime | None
