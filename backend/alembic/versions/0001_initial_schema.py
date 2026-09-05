"""initial schema: users, patient profiles, conditions, regimens, audit log

Revision ID: 0001
Revises:
Create Date: 2026-09-05

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_role = postgresql.ENUM("CLINICIAN", "PATIENT", name="user_role")
biological_sex = postgresql.ENUM("FEMALE", "MALE", "INTERSEX", name="biological_sex")
audit_action_type = postgresql.ENUM(
    "VIEW", "CREATE", "UPDATE", "DELETE", "EXPORT", "LOGIN", name="audit_action_type"
)


def upgrade() -> None:
    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    biological_sex.create(bind, checkfirst=True)
    audit_action_type.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "patient_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("legal_name", sa.String(512), nullable=False),
        sa.Column("date_of_birth", sa.String(512), nullable=False),
        sa.Column("medical_record_number", sa.String(512), nullable=False),
        sa.Column("emergency_contact", sa.Text(), nullable=True),
        sa.Column("biological_sex", biological_sex, nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_patient_profiles_user_id", "patient_profiles", ["user_id"], unique=True)
    op.create_index("ix_patient_profiles_biological_sex", "patient_profiles", ["biological_sex"])
    op.create_index("ix_patient_profiles_age", "patient_profiles", ["age"])

    op.create_table(
        "patient_conditions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patient_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("condition_name", sa.String(255), nullable=False),
        sa.Column("icd10_code", sa.String(16), nullable=True),
        sa.Column("diagnosed_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_patient_conditions_patient_id", "patient_conditions", ["patient_id"])
    op.create_index("ix_patient_conditions_condition_name", "patient_conditions", ["condition_name"])
    op.create_index("ix_patient_conditions_icd10_code", "patient_conditions", ["icd10_code"])

    op.create_table(
        "patient_regimens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patient_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pubchem_cid", sa.Integer(), nullable=False),
        sa.Column("drug_name", sa.String(255), nullable=False),
        sa.Column("dosage", sa.String(128), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "prescriber_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_patient_regimens_patient_id", "patient_regimens", ["patient_id"])
    op.create_index("ix_patient_regimens_pubchem_cid", "patient_regimens", ["pubchem_cid"])
    op.create_index("ix_patient_regimens_end_date", "patient_regimens", ["end_date"])
    op.create_index("ix_patient_regimens_prescriber_id", "patient_regimens", ["prescriber_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "accessor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "target_patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patient_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action_type", audit_action_type, nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_logs_accessor_user_id", "audit_logs", ["accessor_user_id"])
    op.create_index("ix_audit_logs_target_patient_id", "audit_logs", ["target_patient_id"])
    op.create_index("ix_audit_logs_action_type", "audit_logs", ["action_type"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])

    # Enforce append-only semantics at the database level: no UPDATE/DELETE on
    # audit_logs, even from a compromised or misused application credential.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_no_update
        BEFORE UPDATE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_no_delete
        BEFORE DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation()")

    op.drop_table("audit_logs")
    op.drop_table("patient_regimens")
    op.drop_table("patient_conditions")
    op.drop_table("patient_profiles")
    op.drop_table("users")

    bind = op.get_bind()
    audit_action_type.drop(bind, checkfirst=True)
    biological_sex.drop(bind, checkfirst=True)
    user_role.drop(bind, checkfirst=True)
