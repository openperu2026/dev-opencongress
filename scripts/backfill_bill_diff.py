"""Backfill `Bill.bill_diff` from existing `bill_differences` rows."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.database import models as db_models
from backend.database.crud.pipeline_bills import refresh_bill_diff_flag


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    engine = create_engine(settings.DB_URL)
    Session = sessionmaker(bind=engine)

    stmt = select(db_models.Bill.id).order_by(db_models.Bill.id)
    if args.limit:
        stmt = stmt.limit(args.limit)

    updated = 0
    errors = 0

    with Session() as db:
        bill_ids = db.scalars(stmt).all()
        logger.info(f"Backfilling bill_diff for {len(bill_ids)} bill(s)")

        for bill_id in bill_ids:
            try:
                if refresh_bill_diff_flag(db, bill_id):
                    updated += 1
                db.commit()
            except Exception as exc:
                logger.exception(f"Failed for bill_id={bill_id}: {exc}")
                db.rollback()
                errors += 1

    logger.info(f"Done. bill_diff=True for {updated} bill(s), errors={errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
