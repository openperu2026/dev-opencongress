"""Add model_cost_ledger table

Revision ID: c835922c2b00
Revises: 32c12530078f
Create Date: 2026-08-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c835922c2b00"
down_revision: Union[str, Sequence[str], None] = "32c12530078f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "model_cost_ledger",
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("total_cost_usd", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("model"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("model_cost_ledger")
