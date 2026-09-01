"""Add attendance.bancada_id and a membership as-of-date lookup index

Revision ID: b3f7a1d9c246
Revises: c835922c2b00
Create Date: 2026-08-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3f7a1d9c246"
down_revision: Union[str, Sequence[str], None] = "c835922c2b00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "attendance",
        sa.Column("bancada_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "attendance_bancada_id_fkey",
        "attendance",
        "organizations",
        ["bancada_id"],
        ["org_id"],
    )
    op.create_index("ix_attendance_bancada_id", "attendance", ["bancada_id"])

    op.create_index(
        "ix_membership_person_org_type_dates",
        "memberships",
        ["person_id", "org_type", "start_date", "end_date"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_membership_person_org_type_dates", table_name="memberships")
    op.drop_index("ix_attendance_bancada_id", table_name="attendance")
    op.drop_constraint("attendance_bancada_id_fkey", "attendance", type_="foreignkey")
    op.drop_column("attendance", "bancada_id")
