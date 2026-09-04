"""Add congresistas.congresista_id -- stable cross-term matching key

Revision ID: d4e9a1c6f2b8
Revises: c3f8b1a9d2e4
Create Date: 2026-09-03 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e9a1c6f2b8"
down_revision: Union[str, Sequence[str], None] = "c3f8b1a9d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "congresistas",
        sa.Column("congresista_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_congresistas_congresista_id",
        "congresistas",
        ["congresista_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_congresistas_congresista_id", table_name="congresistas")
    op.drop_column("congresistas", "congresista_id")
