"""Backfill `photo_bytes` for congresistas that don't yet have one.

Pass --force to instead resync EVERY congresista's photo_bytes from their
current photo_url, regardless of whether one is already stored -- useful
for a one-time refresh of already-drifted data (photo_url updated to a new
term's URL while photo_bytes still holds the old download, with no stored
record of which URL a given photo_bytes came from to detect that
automatically)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.database import models as db_models
from backend.scrapers.congresista_photos import sync_photo


def build_query(*, force: bool, limit: int | None = None):
    stmt = select(db_models.Congresista).order_by(db_models.Congresista.id)
    if not force:
        stmt = stmt.where(db_models.Congresista.photo_bytes.is_(None))
    if limit:
        stmt = stmt.limit(limit)
    return stmt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="Seconds to sleep between downloads (default: 0.25).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Resync ALL congresistas' photos from their current photo_url, "
            "not just ones missing a photo."
        ),
    )
    args = parser.parse_args()

    engine = create_engine(settings.DB_URL)
    Session = sessionmaker(bind=engine)

    stmt = build_query(force=args.force, limit=args.limit)

    updated = 0
    skipped = 0
    errors = 0

    with Session() as db:
        rows = db.scalars(stmt).all()
        logger.info(f"Processing {len(rows)} congresista(s)")

        for cong in rows:
            try:
                if sync_photo(db, cong, force=args.force):
                    db.commit()
                    updated += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.exception(f"Failed for {cong.id} ({cong.full_name}): {exc}")
                db.rollback()
                errors += 1

            if args.sleep > 0:
                time.sleep(args.sleep)

    logger.info(f"Done. updated={updated} skipped={skipped} errors={errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
