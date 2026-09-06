"""patient_transfers: clinician-to-clinician transfer gated on patient OTP consent

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Not pre-created via .create(checkfirst=True) -- postgresql.ENUM has
# create_type=True by default, so op.create_table() below already emits
# CREATE TYPE the first time this enum object appears as a column type.
transfer_status = postgresql.ENUM(
    "PENDING_PATIENT_CONSENT", "APPROVED", "DECLINED", "CANCELLED", "LOCKED", name="transfer_status"
)


def upgrade() -> None:
    op.create_table(
        "patient_transfers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patient_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_clinician_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "to_clinician_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", transfer_status, nullable=False, server_default="PENDING_PATIENT_CONSENT"),
        sa.Column("otp_hash", sa.String(64), nullable=False),
        sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts_remaining", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_patient_transfers_patient_id", "patient_transfers", ["patient_id"])
    op.create_index("ix_patient_transfers_status", "patient_transfers", ["status"])

    # Only one open consent request per patient at a time -- a second POST
    # while one is pending returns 409 rather than racing two OTP flows.
    op.create_index(
        "uq_patient_transfers_one_pending",
        "patient_transfers",
        ["patient_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING_PATIENT_CONSENT'"),
    )


def downgrade() -> None:
    op.drop_index("uq_patient_transfers_one_pending", table_name="patient_transfers")
    op.drop_index("ix_patient_transfers_status", table_name="patient_transfers")
    op.drop_index("ix_patient_transfers_patient_id", table_name="patient_transfers")
    op.drop_table("patient_transfers")
    transfer_status.drop(op.get_bind(), checkfirst=True)
