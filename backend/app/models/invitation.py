from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class UserInvitation(Base):
    """A single-use, expiring invite that lets a patient set their first password.

    We never email a password. The clinician creates the account with no
    password at all, and this token is the only thing that can set one --
    which keeps a reusable credential out of the patient's inbox and out of
    every mail server between here and there.

    Only the SHA-256 of the token is stored, for the same reason passwords are
    hashed: a database leak shouldn't hand over working invites. The plaintext
    exists only in the email.
    """

    __tablename__ = "user_invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Who issued it -- nullable so removing a clinician doesn't erase the record.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])

    def is_redeemable(self, now: dt.datetime) -> bool:
        return self.used_at is None and self.expires_at > now
