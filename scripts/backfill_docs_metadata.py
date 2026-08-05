"""Backfill file_size and num_pages for raw bill/motion documents missing them."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.database.raw_models import RawBillDocument, RawMotionDocument
from backend.scrapers.docs_metadata import sync_document_metadata

MODEL_CHOICES = {
    "bills": RawBillDocument,
    "motions": RawMotionDocument,
}

ORDER_COLUMN = {
    RawBillDocument: RawBillDocument.bill_id,
    RawMotionDocument: RawMotionDocument.motion_id,
}


def process_model(
    db: Session, model: type, *, limit: int | None, sleep: float
) -> tuple[int, int, int]:
    stmt = (
        select(model)
        .where(or_(model.file_size.is_(None), model.num_pages.is_(None)))
        .order_by(ORDER_COLUMN[model], model.step_id, model.file_id)
    )
    if limit:
        stmt = stmt.limit(limit)

    updated = skipped = errors = 0
    rows = db.scalars(stmt).all()
    logger.info(f"Processing {len(rows)} {model.__tablename__} row(s)")

    for row in rows:
        try:
            if sync_document_metadata(db, row):
                db.commit()
                updated += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.exception(
                f"Failed for {model.__tablename__} {row.step_id}/{row.file_id}: {exc}"
            )
            db.rollback()
            errors += 1

        if sleep > 0:
            time.sleep(sleep)

    return updated, skipped, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        choices=["bills", "motions", "all"],
        default="all",
        help="Which raw document table to backfill (default: all).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max rows to process per table (applied independently to each table when --model=all).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="Seconds to sleep between downloads (default: 0.25).",
    )
    args = parser.parse_args()

    engine = create_engine(settings.DB_URL)
    Session = sessionmaker(bind=engine)

    targets = (
        list(MODEL_CHOICES.values())
        if args.model == "all"
        else [MODEL_CHOICES[args.model]]
    )

    total_updated = total_skipped = total_errors = 0

    with Session() as db:
        for model in targets:
            updated, skipped, errors = process_model(
                db, model, limit=args.limit, sleep=args.sleep
            )
            total_updated += updated
            total_skipped += skipped
            total_errors += errors

    logger.info(
        f"Done. updated={total_updated} skipped={total_skipped} errors={total_errors}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
