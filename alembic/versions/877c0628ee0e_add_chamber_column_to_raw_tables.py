"""add_chamber_column_to_raw_tables

Revision ID: 877c0628ee0e
Revises: 20260813_bill_vote_column
Create Date: 2026-08-31 21:50:20.698866

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "877c0628ee0e"
down_revision: Union[str, Sequence[str], None] = "20260813_bill_vote_column"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = ("raw_congresistas", "raw_bancadas", "raw_committees", "raw_organizations")


def upgrade() -> None:
    """Add nullable chamber column to raw tables that need bicameral chamber attribution.

    Purely additive: new nullable column, no default requiring a table rewrite.
    Existing rows get NULL, which the process layer already treats as "legacy/unspecified,
    defaults to Diputados" (see backend/core/constants.py::CHAMBER_LABEL_TO_ORG_NAME).
    """
    for table in TABLES:
        op.add_column(table, sa.Column("chamber", sa.String(), nullable=True))


def downgrade() -> None:
    """Drop the chamber column from raw tables."""
    for table in TABLES:
        op.drop_column(table, "chamber")
