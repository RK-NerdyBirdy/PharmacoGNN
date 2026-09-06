"""interaction_reports: async, frozen drug-interaction analysis snapshots

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Not pre-created via .create(checkfirst=True) -- postgresql.ENUM has
# create_type=True by default, so op.create_table() below already emits
# CREATE TYPE the first time this enum object appears as a column type.
report_status = postgresql.ENUM("PENDING", "COMPLETE", "FAILED", name="report_status")


def upgrade() -> None:
    op.create_table(
        "interaction_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patient_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", report_status, nullable=False, server_default="PENDING"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("file_path", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_interaction_reports_patient_id", "interaction_reports", ["patient_id"])
    op.create_index("ix_interaction_reports_status", "interaction_reports", ["status"])
    op.create_index("ix_interaction_reports_deleted_at", "interaction_reports", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_interaction_reports_deleted_at", table_name="interaction_reports")
    op.drop_index("ix_interaction_reports_status", table_name="interaction_reports")
    op.drop_index("ix_interaction_reports_patient_id", table_name="interaction_reports")
    op.drop_table("interaction_reports")
    report_status.drop(op.get_bind(), checkfirst=True)
