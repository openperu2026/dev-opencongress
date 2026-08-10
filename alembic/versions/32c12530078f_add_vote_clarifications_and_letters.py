"""Add vote/attendance clarifications, member letters, and new enum values

Revision ID: 32c12530078f
Revises: 5cd01ffba69d
Create Date: 2026-08-05 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "32c12530078f"
down_revision: Union[str, Sequence[str], None] = "5cd01ffba69d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_VOTE_OPTION_VALUES = (
    "Ausente",
    "Con licencia",
    "Suspendido",
    "Fallecido",
    "Presidiendo",
)
NEW_ATTENDANCE_STATUS_VALUES = (
    "Fallecido",
    "Presidiendo",
)

# References to the already-existing native enum types (created by earlier
# migrations/baseline). create_type=False so create_table below doesn't try
# to CREATE TYPE a type that already exists.
vote_option_enum = postgresql.ENUM(name="vote_option", create_type=False)
attendance_status_enum = postgresql.ENUM(name="attendance_status", create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    for value in NEW_VOTE_OPTION_VALUES:
        op.execute(f"ALTER TYPE vote_option ADD VALUE IF NOT EXISTS '{value}'")
    for value in NEW_ATTENDANCE_STATUS_VALUES:
        op.execute(f"ALTER TYPE attendance_status ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        "vote_clarifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("vote_event_id", sa.String(), nullable=False),
        sa.Column("voter_id", sa.Integer(), nullable=True),
        sa.Column("member_name", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=False),
        sa.Column("roll_value", vote_option_enum, nullable=True),
        sa.Column("clarified_value", vote_option_enum, nullable=True),
        sa.CheckConstraint(
            "source IN ('president_note', 'member_letter')",
            name="ck_vote_clarification_source",
        ),
        sa.ForeignKeyConstraint(["vote_event_id"], ["vote_events.vote_event_id"]),
        sa.ForeignKeyConstraint(["voter_id"], ["congresistas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vote_clarifications_event", "vote_clarifications", ["vote_event_id"]
    )
    op.create_index("ix_vote_clarifications_voter", "vote_clarifications", ["voter_id"])

    op.create_table(
        "attendance_clarifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("voter_id", sa.Integer(), nullable=True),
        sa.Column("member_name", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=False),
        sa.Column("roster_value", attendance_status_enum, nullable=True),
        sa.Column("clarified_value", attendance_status_enum, nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["vote_events.vote_event_id"]),
        sa.ForeignKeyConstraint(["voter_id"], ["congresistas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attendance_clarifications_event", "attendance_clarifications", ["event_id"]
    )
    op.create_index(
        "ix_attendance_clarifications_voter", "attendance_clarifications", ["voter_id"]
    )

    op.create_table(
        "member_letters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bill_id", sa.String(), nullable=True),
        sa.Column("motion_id", sa.String(), nullable=True),
        sa.Column("voter_id", sa.Integer(), nullable=True),
        sa.Column("member_name", sa.String(), nullable=False),
        sa.Column("party", sa.String(), nullable=True),
        sa.Column("letter_date", sa.Date(), nullable=True),
        sa.Column("subject_reference", sa.String(), nullable=False),
        sa.Column("requested_attendance", attendance_status_enum, nullable=True),
        sa.Column("requested_vote", vote_option_enum, nullable=True),
        sa.CheckConstraint(
            "(bill_id IS NOT NULL) OR (motion_id IS NOT NULL)",
            name="ck_member_letter_has_target",
        ),
        sa.ForeignKeyConstraint(["bill_id"], ["bills.id"]),
        sa.ForeignKeyConstraint(["motion_id"], ["motions.id"]),
        sa.ForeignKeyConstraint(["voter_id"], ["congresistas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_member_letters_bill_id", "member_letters", ["bill_id"])
    op.create_index("ix_member_letters_motion_id", "member_letters", ["motion_id"])
    op.create_index("ix_member_letters_voter_id", "member_letters", ["voter_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("member_letters")
    op.drop_table("attendance_clarifications")
    op.drop_table("vote_clarifications")
    raise NotImplementedError(
        "Postgres does not support removing enum values; the table drops above "
        "have run, but rolling back the vote_option/attendance_status value "
        "additions requires restoring from a pre-migration backup."
    )
