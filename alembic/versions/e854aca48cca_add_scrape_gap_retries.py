"""Add scrape_gap_retries table

Revision ID: e854aca48cca
Revises: d4e9a1c6f2b8
Create Date: 2026-09-04 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e854aca48cca"
down_revision: Union[str, Sequence[str], None] = "d4e9a1c6f2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "scrape_gap_retries",
        sa.Column("raw_model_name", sa.String(), nullable=False),
        sa.Column("gap_id", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("skipped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("raw_model_name", "gap_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("scrape_gap_retries")
