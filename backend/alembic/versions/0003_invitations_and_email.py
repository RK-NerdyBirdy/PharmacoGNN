"""invite-based onboarding: user_invitations, email_deliveries, nullable password

users.hashed_password becomes nullable so a clinician-created patient can
exist before any password does -- the emailed invite token is the only thing
that sets the first one, which keeps a working credential out of the patient's
inbox entirely.

Existing rows all have a password already, so widening the column is safe and
needs no backfill. The reverse is not safe, which is why downgrade() refuses
to run while any password-less account exists rather than silently deleting
those accounts or inventing passwords for them.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

email_status = postgresql.ENUM("SENT", "FAILED", name="email_status")


def upgrade() -> None:
    op.alter_column("users", "hashed_password", existing_type=sa.String(255), nullable=True)

    op.create_table(
        "user_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_invitations_user_id", "user_invitations", ["user_id"])
    op.create_index("ix_user_invitations_token_hash", "user_invitations", ["token_hash"], unique=True)

    op.create_table(
        "email_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("to_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("template", sa.String(64), nullable=False),
        sa.Column("status", email_status, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "related_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_email_deliveries_to_email", "email_deliveries", ["to_email"])
    op.create_index("ix_email_deliveries_status", "email_deliveries", ["status"])
    op.create_index("ix_email_deliveries_related_user_id", "email_deliveries", ["related_user_id"])


def downgrade() -> None:
    op.drop_index("ix_email_deliveries_related_user_id", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_status", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_to_email", table_name="email_deliveries")
    op.drop_table("email_deliveries")
    email_status.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_user_invitations_token_hash", table_name="user_invitations")
    op.drop_index("ix_user_invitations_user_id", table_name="user_invitations")
    op.drop_table("user_invitations")

    # Refuse rather than destroy: any account still awaiting activation has no
    # password to restore, and NOT NULL cannot be re-applied around it.
    pending = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM users WHERE hashed_password IS NULL")
    )
    if pending:
        raise RuntimeError(
            f"{pending} account(s) have no password (never activated). Downgrading would "
            "require deleting them or fabricating passwords. Resolve those rows first."
        )
    op.alter_column("users", "hashed_password", existing_type=sa.String(255), nullable=False)
