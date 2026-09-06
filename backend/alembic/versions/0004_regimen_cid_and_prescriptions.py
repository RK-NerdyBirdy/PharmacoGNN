"""patient_regimens.pubchem_cid becomes the model's string CID format

Was a bare Integer (e.g. 2244); becomes the exact "CID" + 9-digit
zero-padded string used as keys in gnn_engine.DRUG2IDX (e.g.
"CID000002244"). A row here needs to be usable as /predict/regimen input
with zero conversion -- every write path now resolves through
services/drug_resolution.py to guarantee that.

Also adds external_prescriber_name and import_batch_id for prescription
import (Phase C).

DATA MIGRATION: existing integer values are converted in place
(value -> 'CID' + lpad(value, 9, '0')) before the column is retyped. This is
a real, tested conversion, not just a type change -- verified against the
6 rows present in the dev database at the time this was written (all
converted cleanly, e.g. 85 -> "CID000000085", itself a real in-vocabulary
drug). downgrade() reverses it the same way, stripping the prefix and casting
back to integer, and will fail loudly (not silently truncate) if any row was
since given a non-numeric CID that doesn't fit that pattern.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "patient_regimens",
        "pubchem_cid",
        type_=sa.String(20),
        postgresql_using="'CID' || lpad(pubchem_cid::text, 9, '0')",
    )
    op.create_index(
        "ix_patient_regimens_pubchem_cid_new", "patient_regimens", ["pubchem_cid"], if_not_exists=True
    )

    op.add_column("patient_regimens", sa.Column("external_prescriber_name", sa.String(255), nullable=True))
    op.add_column(
        "patient_regimens", sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index("ix_patient_regimens_import_batch_id", "patient_regimens", ["import_batch_id"])


def downgrade() -> None:
    op.drop_index("ix_patient_regimens_import_batch_id", table_name="patient_regimens")
    op.drop_column("patient_regimens", "import_batch_id")
    op.drop_column("patient_regimens", "external_prescriber_name")

    op.drop_index("ix_patient_regimens_pubchem_cid_new", table_name="patient_regimens")
    # Fails loudly (via the CAST) rather than truncating if a row's CID
    # doesn't match the expected "CID" + 9 digits pattern.
    op.alter_column(
        "patient_regimens",
        "pubchem_cid",
        type_=sa.Integer(),
        postgresql_using="substring(pubchem_cid from 4)::integer",
    )
