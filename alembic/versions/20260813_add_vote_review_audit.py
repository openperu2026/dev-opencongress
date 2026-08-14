"""Add vote_review_audit table

Revision ID: 20260813_vote_review_audit
Revises: 20260809_congresista_aliases
Create Date: 2026-08-13 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260813_vote_review_audit"
down_revision: Union[str, Sequence[str], None] = "20260809_congresista_aliases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "vote_review_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("vote_event_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("old_value", sa.String(), nullable=True),
        sa.Column("new_value", sa.String(), nullable=True),
        sa.Column("reviewer_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('vote','attendance')",
            name="ck_review_audit_target_type",
        ),
        sa.CheckConstraint(
            "action IN ('verified','corrected','flagged')",
            name="ck_review_audit_action",
        ),
        sa.ForeignKeyConstraint(["vote_event_id"], ["vote_events.vote_event_id"]),
        sa.ForeignKeyConstraint(["target_id"], ["congresistas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_audit_event_target",
        "vote_review_audit",
        ["vote_event_id", "target_type", "target_id", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_review_audit_event_target", table_name="vote_review_audit")
    op.drop_table("vote_review_audit")
