"""Backfill file_size and num_pages for raw bill/motion documents missing them."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import sessionmaker
from tqdm import tqdm

from backend.config import settings
from backend.database.raw_models import RawBillDocument, RawMotionDocument
from backend.scrapers.docs_metadata import sync_document_metadata

MODEL_CHOICES = {
    "bills": RawBillDocument,
    "motions": RawMotionDocument,
}

PK_COLUMNS = {
    RawBillDocument: ("bill_id", "step_id", "file_id"),
    RawMotionDocument: ("motion_id", "step_id", "file_id"),
}


def _pending_pks(Session, model: type, *, limit: int | None) -> list[tuple]:
    cols = PK_COLUMNS[model]
    with Session() as db:
        stmt = (
            select(model)
            .where(or_(model.file_size.is_(None), model.num_pages.is_(None)))
            .order_by(*(getattr(model, c) for c in cols))
        )
        if limit:
            stmt = stmt.limit(limit)
        rows = db.scalars(stmt).all()
        return [tuple(getattr(row, c) for c in cols) for row in rows]


def _sync_one(Session, model: type, pk: tuple) -> tuple[bool, str | None]:
    """Runs inside a worker thread: opens its own session, never shares one across threads."""
    with Session() as db:
        row = db.get(model, pk)
        if row is None:
            return False, "row no longer exists"
        try:
            updated = sync_document_metadata(db, row)
        except Exception as exc:
            db.rollback()
            return False, str(exc)
        if updated:
            db.commit()
        return updated, None


def process_model(
    Session, model: type, *, limit: int | None, workers: int
) -> tuple[int, int, int]:
    pks = _pending_pks(Session, model, limit=limit)
    logger.info(
        f"Processing {len(pks)} {model.__tablename__} row(s) with {workers} workers"
    )

    updated = skipped = errors = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_pk = {
            executor.submit(_sync_one, Session, model, pk): pk for pk in pks
        }
        for future in tqdm(
            as_completed(future_to_pk), total=len(pks), desc=model.__tablename__
        ):
            pk = future_to_pk[future]
            try:
                ok, err = future.result()
            except Exception as exc:
                ok, err = False, str(exc)

            if err:
                logger.warning(f"Failed for {model.__tablename__} {pk}: {err}")
                errors += 1
            elif ok:
                updated += 1
            else:
                skipped += 1

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
        "--workers",
        type=int,
        default=15,
        help="Concurrent download threads (default: 15, matching orchestrator.py).",
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

    for model in targets:
        updated, skipped, errors = process_model(
            Session, model, limit=args.limit, workers=args.workers
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
