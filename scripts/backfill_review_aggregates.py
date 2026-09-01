"""Backfill VoteEvent tallies and VoteCounts for vote events that were
corrected through the review tool (review_app/) before
crud_review.resync_vote_event_aggregates existed -- apply_correction now
re-syncs both automatically on every future correction, but events
reviewed before that fix landed are still stuck with whatever
VoteEvent/VoteCounts values the original ETL load computed, even though
their underlying Vote rows have since changed.

Also refreshes each affected Vote's bancada_id from the person's current
BancadaMembership as of the event's date first (the same resolution
apply_correction itself now uses) -- a vote added through the review tool
before that fix could have bancada_id=None, which would otherwise make it
invisible in every bancada-grouped count even after the resync.

Scoped to "reviewed" events only (anything with a logged vote_review_audit
correction) -- not every VoteEvent in the database. Safe to re-run: an
event that's already been through the current (fixed) apply_correction
path recomputes to the same values it already has, so this is a one-time
catch-up for pre-fix corrections, not a recurring job.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.database.crud.pipeline_core import find_active_bancada_for_person
from backend.database.crud.review import resync_vote_event_aggregates
from backend.database.models import Vote, VoteCounts, VoteEvent
import review_app.models  # noqa: F401 -- registers VoteReviewAudit on Base.metadata
from review_app.models import VoteReviewAudit


def find_reviewed_vote_event_ids(db: Session, *, limit: int | None) -> list[str]:
    """Every vote_event_id with at least one logged vote correction."""
    ids = db.scalars(
        select(VoteReviewAudit.vote_event_id)
        .where(
            VoteReviewAudit.target_type == "vote",
            VoteReviewAudit.action == "corrected",
        )
        .distinct()
        .order_by(VoteReviewAudit.vote_event_id)
    ).all()
    if limit:
        ids = ids[:limit]
    return ids


def backfill_event(db: Session, vote_event_id: str, *, dry_run: bool) -> dict:
    """
    Refresh bancada_id on this event's Vote rows, then resync its
    VoteEvent tallies + VoteCounts. Always runs the resync inside the
    session first (so a dry run sees the real post-resync numbers), then
    either commits or rolls back.
    """
    event = db.get(VoteEvent, vote_event_id)
    if event is None:
        return {"vote_event_id": vote_event_id, "skipped": "event not found"}

    before = (event.votes_in_favor, event.votes_against, event.votes_abstention)

    votes = db.scalars(select(Vote).where(Vote.vote_event_id == vote_event_id)).all()
    bancada_updates = 0
    for vote in votes:
        org = find_active_bancada_for_person(db, vote.voter_id, event.event_date)
        if org is not None and org.org_id != vote.bancada_id:
            vote.bancada_id = org.org_id
            bancada_updates += 1

    db.flush()
    resync_vote_event_aggregates(db, vote_event_id)
    after = (event.votes_in_favor, event.votes_against, event.votes_abstention)
    vote_counts_rows = (
        db.query(VoteCounts).filter_by(vote_event_id=vote_event_id).count()
    )

    result = {
        "vote_event_id": vote_event_id,
        "bancada_updates": bancada_updates,
        "tally_before": before,
        "tally_after": after,
        "vote_counts_rows": vote_counts_rows,
        "changed": before != after or bancada_updates > 0,
    }

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of events processed (debugging).",
    )
    args = parser.parse_args()

    engine = create_engine(settings.DB_URL)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        event_ids = find_reviewed_vote_event_ids(db, limit=args.limit)
        logger.info(f"Found {len(event_ids)} reviewed vote event(s) to check.")

        changed = 0
        for vote_event_id in event_ids:
            result = backfill_event(db, vote_event_id, dry_run=args.dry_run)
            if result.get("skipped"):
                logger.warning(f"[{vote_event_id}] skipped: {result['skipped']}")
                continue
            if result["changed"]:
                changed += 1
                logger.info(f"[{vote_event_id}] {result}")

        suffix = " (dry run, nothing written)" if args.dry_run else ""
        logger.info(
            f"Done. {changed}/{len(event_ids)} event(s) had stale aggregates{suffix}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
