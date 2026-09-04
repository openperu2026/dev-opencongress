"""Backfill congresista_id on already-processed Congresista rows using the
mined cong_info_2021_2026.json / cong_info_2026_2031.json files.

_process_congresistas only touches unprocessed RawCongresista rows, so
already-processed Congresista rows never get congresista_id populated just
because gen_congresistas_df/process_profile_content now know how to set it
-- this script closes that gap for existing data. Run it after
`make gen-congresistas-2026-2031` has produced (or updated)
cong_info_2026_2031.json, and rerun it periodically as that file's
coverage grows.

Additive only: never deletes a row, never overwrites an already-populated
congresista_id. Matches by normalize_name(full_name, sort_tokens=True) on
both sides -- order-independent, so it works regardless of which order a
row's stored full_name happens to be in.

Defaults to a dry run (report only). Pass --apply to actually write.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.config import settings, directories
from backend.database import models as db_models
from backend.process.congresistas import get_cong_data
from backend.process.utils import normalize_name

CONG_JSON = directories.PROCESSED_DATA / "cong_info_2021_2026.json"
CONG_JSON_2026 = directories.PROCESSED_DATA / "cong_info_2026_2031.json"


def build_name_index() -> dict[str, int]:
    """Merge both mined files into one normalized-name -> congresista_id
    index. 2026-2031 entries are merged in after legacy ones so a person
    known to both files keeps a single congresista_id -- they should
    already agree (per the confirmed cross-term stability), this is just a
    deterministic tie-break, not expected to matter in practice.
    """
    index: dict[str, int] = {}

    if CONG_JSON.exists():
        for entry in get_cong_data(CONG_JSON).values():
            cid = entry.get("congresista_id")
            if cid is not None:
                index[normalize_name(entry["full_name"], sort_tokens=True)] = cid

    if CONG_JSON_2026.exists():
        for entry in get_cong_data(CONG_JSON_2026, leg_period="2026-2031").values():
            cid = entry.get("congresista_id")
            if cid is not None:
                index[normalize_name(entry["full_name"], sort_tokens=True)] = cid

    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes. Without this flag, only reports what would change.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Cap rows processed (debugging)."
    )
    args = parser.parse_args()

    name_index = build_name_index()
    logger.info(f"Loaded {len(name_index)} known congresista_id mapping(s)")

    engine = create_engine(settings.DB_URL)
    SessionLocal = sessionmaker(bind=engine)

    backfilled = 0
    unmatched = 0

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(db_models.Congresista).where(
                    db_models.Congresista.congresista_id.is_(None)
                )
            ).all()
        )
        if args.limit is not None:
            rows = rows[: args.limit]

        logger.info(f"Found {len(rows)} Congresista row(s) missing congresista_id")

        for cong in rows:
            key = normalize_name(cong.full_name, sort_tokens=True)
            cid = name_index.get(key)
            if cid is None:
                unmatched += 1
                continue
            logger.info(f"[congresista id={cong.id}] congresista_id: None -> {cid}")
            if args.apply:
                cong.congresista_id = cid
            backfilled += 1

        if args.apply:
            db.commit()
            logger.info(
                f"Applied: backfilled {backfilled} row(s), {unmatched} unmatched"
            )
        else:
            logger.info(
                f"Dry run: would backfill {backfilled} row(s), {unmatched} unmatched "
                "-- re-run with --apply to write changes"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
