"""
ORM model(s) owned by the review tool (`review_app/`), not the core
pipeline. Kept out of `backend/database/models.py` since nothing outside
this tool reads or writes them -- mirrors `backend/database/raw_models.py`'s
pattern (own module, same `Base`, registered onto the shared metadata via a
side-effect import in `alembic/env.py`).

Import-light by design: SQLAlchemy + `backend.database.models.Base` only,
no Flask, no `review_app.app`/`routes`. `alembic/env.py` imports this
module for its side effect, so a broken import here would break `alembic`
for the whole repo, not just this feature.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.models import Base


class VoteReviewAudit(Base):
    """
    Append-only log of reviewer actions against a `Vote`/`Attendance` row.
    Doubles as "current status" (latest row per target) so no second
    status table is needed -- callers select the most recent row per
    (vote_event_id, target_type, target_id) for a status badge.

    Attributes:
        vote_event_id (str): The vote event this action is about.
        target_type (str): 'vote' or 'attendance'.
        target_id (int): The congresista this row is about.
        action (str): 'verified', 'corrected', or 'flagged'.
        old_value (str | None): The value before a correction, if any.
        new_value (str | None): The value after a correction, if any.
        reviewer_name (str): Free-text attribution, no user table.
        created_at (datetime): When the action was recorded.
    """

    __tablename__ = "vote_review_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    vote_event_id: Mapped[str] = mapped_column(
        ForeignKey("vote_events.vote_event_id"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(nullable=False)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("congresistas.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(nullable=False)
    old_value: Mapped[str | None] = mapped_column(nullable=True)
    new_value: Mapped[str | None] = mapped_column(nullable=True)
    reviewer_name: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        CheckConstraint(
            "target_type IN ('vote','attendance')",
            name="ck_review_audit_target_type",
        ),
        CheckConstraint(
            "action IN ('verified','corrected','flagged')",
            name="ck_review_audit_action",
        ),
        Index(
            "ix_review_audit_event_target",
            "vote_event_id",
            "target_type",
            "target_id",
            "created_at",
        ),
    )
