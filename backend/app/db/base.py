from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import String, Text, TypeDecorator

from app.core.security import decrypt_value, encrypt_value


class Base(DeclarativeBase):
    """Shared declarative base; Base.metadata is what Alembic autogenerate targets."""


class TimestampMixin:
    """created_at / updated_at columns shared by mutable domain tables.

    Deliberately NOT used by AuditLog: that table is append-only and has no
    updated_at column at all, so mutation is structurally, not just
    conventionally, unsupported.
    """

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EncryptedString(TypeDecorator):
    """AES-256-GCM-encrypted VARCHAR for short PHI fields (names, IDs, DOB-as-text).

    512 chars comfortably covers the ~1.4x base64 expansion of a 12-byte nonce
    + 16-byte auth tag + a few hundred bytes of plaintext.
    """

    impl = String(512)
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        return encrypt_value(value)

    def process_result_value(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        return decrypt_value(value)


class EncryptedText(EncryptedString):
    """AES-256-GCM-encrypted TEXT for longer/unbounded PHI fields (e.g. emergency_contact)."""

    impl = Text()
