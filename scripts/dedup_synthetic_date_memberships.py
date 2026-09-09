"""Cleanup for the synthetic-date membership duplication bug (found 2026-09-09).

chamber_mem/party_mem (and a couple of admin memberships) never carry an
explicit start_date, so _membership_dates always fell back to deriving a
Jul-28-to-Jul-28 window seeded from the scrape timestamp. Re-scraping the
same ongoing membership after a Jul 28 boundary passed shifted that window
forward a year, and upsert_membership's old exact-date match treated it as
a new stint, inserting a duplicate row every year. The matching bug itself
is fixed (upsert_membership's dates_are_synthetic parameter) -- this script
cleans up the duplicate rows that already exist.

Scope is deliberately narrow: only groups of (person_id, org_id, leg_period,
org_type, role) where EVERY row's start_date AND end_date fall exactly on
month=7, day=28 (the synthetic signature) are touched. Real per-stint data
(e.g. committee reassignments, which get a genuinely new row each
legislative year with real, source-confirmed dates that are NOT always
July 28) is never touched, even if it happens to have more than one row.

For each matched group, keeps the row with the latest start_date (the most
current window, matching what the fixed upsert now maintains going
forward) and deletes the rest via the ORM (so the joined-table-inheritance
subtype row -- ChamberMembership/PartyMembership/AdminMembership -- is
deleted correctly alongside its Membership base row).

Defaults to a dry run (report only). Pass --apply to actually delete.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.database import models as db_models
from backend.database.crud.pipeline_core import MEMBERSHIP_MODELS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry run)"
    )
    args = parser.parse_args()

    engine = create_engine(settings.DB_URL)
    DBSession = sessionmaker(bind=engine)

    deleted = 0
    kept = 0
    skipped_groups = 0

    with DBSession() as db:
        groups = db.execute(
            select(
                db_models.Membership.person_id,
                db_models.Membership.org_id,
                db_models.Membership.leg_period,
                db_models.Membership.org_type,
                db_models.Membership.role,
                func.count().label("total"),
            )
            .group_by(
                db_models.Membership.person_id,
                db_models.Membership.org_id,
                db_models.Membership.leg_period,
                db_models.Membership.org_type,
                db_models.Membership.role,
            )
            .having(func.count() > 1)
        ).all()
        logger.info(f"Found {len(groups)} group(s) with more than one row")

        for g in groups:
            rows = (
                db.execute(
                    select(db_models.Membership)
                    .where(
                        db_models.Membership.person_id == g.person_id,
                        db_models.Membership.org_id == g.org_id,
                        db_models.Membership.leg_period == g.leg_period,
                        db_models.Membership.org_type == g.org_type,
                        db_models.Membership.role == g.role,
                    )
                    .order_by(db_models.Membership.start_date.desc())
                )
                .scalars()
                .all()
            )

            all_synthetic = all(
                r.start_date.month == 7
                and r.start_date.day == 28
                and r.end_date.month == 7
                and r.end_date.day == 28
                for r in rows
            )
            if not all_synthetic:
                skipped_groups += 1
                continue

            keep, *rest = rows  # already ordered by start_date desc
            kept += 1
            model = MEMBERSHIP_MODELS[g.org_type]

            for r in rest:
                action = "Deleting" if args.apply else "Would delete"
                logger.info(
                    f"{action} membership id={r.id} (person_id={g.person_id}, org_id={g.org_id}, "
                    f"leg_period={g.leg_period}, org_type={g.org_type}, role={g.role}, "
                    f"start_date={r.start_date}, end_date={r.end_date}) -- keeping id={keep.id} "
                    f"(start_date={keep.start_date}, end_date={keep.end_date})"
                )
                if args.apply:
                    subtype_obj = db.get(model, r.id)
                    db.delete(subtype_obj)
                deleted += 1

        logger.info(
            f"Groups: {kept} matched the synthetic-date signature, {skipped_groups} skipped "
            "(real per-stint data, not touched)"
        )

        if args.apply:
            db.commit()
            logger.info(f"Applied: deleted {deleted} duplicate row(s)")
        else:
            logger.info(
                f"Dry run: would delete {deleted} duplicate row(s) -- re-run with --apply to write changes"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
