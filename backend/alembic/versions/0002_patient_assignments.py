"""patient_assignments: clinician authority over a patient

Access to a patient stops being "holds the CLINICIAN role" and becomes "has an
active assignment row here".

NOTE ON EXISTING DATA: patient_profiles carries no record of which clinician
created it, so there is nothing to derive a backfill from. Existing profiles
are therefore left unassigned, which means no clinician can reach them until
someone is explicitly assigned. That is the fail-closed direction, and the
only rows affected are development/test data.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patient_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patient_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "clinician_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_reason", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_patient_assignments_patient_id", "patient_assignments", ["patient_id"])
    op.create_index("ix_patient_assignments_clinician_id", "patient_assignments", ["clinician_id"])
    op.create_index("ix_patient_assignments_ended_at", "patient_assignments", ["ended_at"])

    # Partial unique indexes: the constraints only apply to *live* assignments,
    # so a patient can be re-assigned to the same clinician after an earlier
    # assignment was ended, and historical rows never collide.
    op.create_index(
        "uq_patient_assignments_active_pair",
        "patient_assignments",
        ["patient_id", "clinician_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        "uq_patient_assignments_active_primary",
        "patient_assignments",
        ["patient_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL AND is_primary"),
    )


def downgrade() -> None:
    op.drop_index("uq_patient_assignments_active_primary", table_name="patient_assignments")
    op.drop_index("uq_patient_assignments_active_pair", table_name="patient_assignments")
    op.drop_index("ix_patient_assignments_ended_at", table_name="patient_assignments")
    op.drop_index("ix_patient_assignments_clinician_id", table_name="patient_assignments")
    op.drop_index("ix_patient_assignments_patient_id", table_name="patient_assignments")
    op.drop_table("patient_assignments")
