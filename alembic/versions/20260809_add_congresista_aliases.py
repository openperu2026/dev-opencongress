"""Add congresista_aliases table

Revision ID: 20260809_congresista_aliases
Revises: 5cd01ffba69d
Create Date: 2026-08-09 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260809_congresista_aliases"
down_revision: Union[str, Sequence[str], None] = "5cd01ffba69d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "congresista_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("congresista_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["congresista_id"],
            ["congresistas.id"],
            name="fk_congresista_aliases_congresista_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_congresista_aliases"),
        sa.UniqueConstraint("name", name="uq_congresista_alias_name"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("congresista_aliases")
