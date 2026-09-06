from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EmailStatus(str, enum.Enum):
    SENT = "SENT"
    FAILED = "FAILED"


class EmailDelivery(Base):
    """Record of every message the backend tried to send.

    Exists to answer the question that actually comes up in support -- "did
    the patient ever get their invite?" -- without which a resend flow is
    blind guesswork.

    Deliberately stores only the subject and template name, never the body:
    bodies would accumulate PHI-adjacent content in a table that has none of
    the encryption the patient tables do.
    """

    __tablename__ = "email_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus, name="email_status", native_enum=True), nullable=False, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
