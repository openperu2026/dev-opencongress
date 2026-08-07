"""Backfill bancada_id on already-loaded Vote/VoteCounts/Attendance/
BillCongresistas/MotionCongresistas rows using the Membership table's
as-of-date lookup (crud_core.find_active_bancada_for_person), instead of
whatever bancada attribution (or lack of one) those rows already carry.

Four independent, resumable passes:
  1. Vote      -- resolved as of VoteEvent.event_date; overwrites bancada_id
                  whenever a membership row covers that date (membership
                  takes priority over the PDF-text fallback already stored).
                  VoteCounts for the affected vote_events are recomputed
                  from the resulting Vote rows.
  2. Attendance -- resolved as of VoteEvent.event_date; only fills rows
                  where bancada_id is currently NULL (no other source
                  exists for attendance).
  3. BillCongresistas -- resolved as of the bill's chamber
                  BillOrganization.presentation_date.
  4. MotionCongresistas -- resolved as of the motion's chamber
                  MotionOrganization.presentation_date.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend import TypeOrganization, VoteOption
from backend.config import settings
from backend.database import models as db_models
from backend.database.crud import pipeline_core as crud_core
from backend.database.crud import pipeline_votes as crud_votes

CHAMBER_ORG_NAME = "Cámara de Diputados"


def backfill_votes(db: Session, *, limit: int | None) -> tuple[int, int]:
    """Returns (votes_updated, vote_events_with_recomputed_counts)."""
    event_ids = db.scalars(
        select(db_models.VoteEvent.vote_event_id).order_by(
            db_models.VoteEvent.vote_event_id
        )
    ).all()
    if limit:
        event_ids = event_ids[:limit]

    votes_updated = 0
    events_touched = 0

    for vote_event_id in event_ids:
        event_date = db.scalar(
            select(db_models.VoteEvent.event_date).where(
                db_models.VoteEvent.vote_event_id == vote_event_id
            )
        )
        votes = db.scalars(
            select(db_models.Vote).where(db_models.Vote.vote_event_id == vote_event_id)
        ).all()

        for vote in votes:
            org = crud_core.find_active_bancada_for_person(
                db, vote.voter_id, event_date
            )
            if org is not None and org.org_id != vote.bancada_id:
                vote.bancada_id = org.org_id
                votes_updated += 1

        db.flush()

        counts: dict[tuple[int | None, VoteOption], int] = {}
        for vote in votes:
            key = (vote.bancada_id, vote.option)
            counts[key] = counts.get(key, 0) + 1
        crud_votes.upsert_vote_counts_for_event(
            db, vote_event_id=vote_event_id, counts=counts
        )
        events_touched += 1
        db.commit()

    return votes_updated, events_touched


def backfill_attendance(db: Session, *, limit: int | None) -> int:
    rows = db.scalars(
        select(db_models.Attendance)
        .join(
            db_models.VoteEvent,
            db_models.VoteEvent.vote_event_id == db_models.Attendance.event_id,
        )
        .where(db_models.Attendance.bancada_id.is_(None))
    ).all()
    if limit:
        rows = rows[:limit]

    updated = 0
    for attendance in rows:
        event_date = db.scalar(
            select(db_models.VoteEvent.event_date).where(
                db_models.VoteEvent.vote_event_id == attendance.event_id
            )
        )
        org = crud_core.find_active_bancada_for_person(
            db, attendance.attendee_id, event_date
        )
        if org is not None:
            attendance.bancada_id = org.org_id
            updated += 1
    db.commit()
    return updated


def backfill_bill_congresistas(db: Session, *, limit: int | None) -> int:
    chamber = crud_core.find_organization(
        db, org_name=CHAMBER_ORG_NAME, org_type=TypeOrganization.CHAMBER
    )
    if chamber is None:
        logger.warning(
            f"Chamber organization {CHAMBER_ORG_NAME!r} not found; skipping bills."
        )
        return 0

    rows = db.scalars(select(db_models.BillCongresistas)).all()
    if limit:
        rows = rows[:limit]

    updated = 0
    for rel in rows:
        presentation_date = db.scalar(
            select(db_models.BillOrganization.presentation_date).where(
                db_models.BillOrganization.bill_id == rel.bill_id,
                db_models.BillOrganization.org_id == chamber.org_id,
            )
        )
        if presentation_date is None:
            continue
        org = crud_core.find_active_bancada_for_person(
            db, rel.person_id, presentation_date
        )
        if org is not None and org.org_id != rel.bancada_id:
            rel.bancada_id = org.org_id
            updated += 1
    db.commit()
    return updated


def backfill_motion_congresistas(db: Session, *, limit: int | None) -> int:
    chamber = crud_core.find_organization(
        db, org_name=CHAMBER_ORG_NAME, org_type=TypeOrganization.CHAMBER
    )
    if chamber is None:
        logger.warning(
            f"Chamber organization {CHAMBER_ORG_NAME!r} not found; skipping motions."
        )
        return 0

    rows = db.scalars(select(db_models.MotionCongresistas)).all()
    if limit:
        rows = rows[:limit]

    updated = 0
    for rel in rows:
        presentation_date = db.scalar(
            select(db_models.MotionOrganization.presentation_date).where(
                db_models.MotionOrganization.motion_id == rel.motion_id,
                db_models.MotionOrganization.org_id == chamber.org_id,
            )
        )
        if presentation_date is None:
            continue
        org = crud_core.find_active_bancada_for_person(
            db, rel.person_id, presentation_date
        )
        if org is not None and org.org_id != rel.bancada_id:
            rel.bancada_id = org.org_id
            updated += 1
    db.commit()
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=["votes", "attendance", "bills", "motions"],
        action="append",
        help="Restrict to specific passes (repeatable). Default: run all.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Cap rows/events per pass (debugging)."
    )
    args = parser.parse_args()
    passes = (
        set(args.only) if args.only else {"votes", "attendance", "bills", "motions"}
    )

    engine = create_engine(settings.DB_URL)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        if "votes" in passes:
            votes_updated, events_touched = backfill_votes(db, limit=args.limit)
            logger.info(
                f"[votes] votes_updated={votes_updated} "
                f"vote_events_recomputed={events_touched}"
            )
        if "attendance" in passes:
            attendance_updated = backfill_attendance(db, limit=args.limit)
            logger.info(f"[attendance] rows_updated={attendance_updated}")
        if "bills" in passes:
            bill_cong_updated = backfill_bill_congresistas(db, limit=args.limit)
            logger.info(f"[bills] bill_congresistas_updated={bill_cong_updated}")
        if "motions" in passes:
            motion_cong_updated = backfill_motion_congresistas(db, limit=args.limit)
            logger.info(f"[motions] motion_congresistas_updated={motion_cong_updated}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
