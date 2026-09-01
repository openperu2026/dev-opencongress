"""
Backfill surname-only aliases for congresistas whose surname is unique
across the table.

Motivated by a 2026-08-18 `make process-votes-from-raw` run: extraction on
cropped/low-resolution scans sometimes returns a roster/roll `full_name`
as a bare surname (no given name, no comma) -- e.g. 'AMURUZ DULANTO'.
`find_congresista`'s fuzzy step can't resolve this (Jaro-Winkler weights
the start of the string, and a bare surname sits at the END of the
canonical "GIVEN SURNAME" format), but its alias step is an exact match
with no such weighting -- so a surname-only alias resolves it directly.

Ambiguous surnames (shared by 2+ congresistas) are skipped entirely: a
bare-surname alias for one of them would guess which person is meant,
risking a silent wrong attribution -- worse than the current "not found"
warning, which at least fails loudly. As of 2026-08-18 there are exactly
2 such pairs (4 people) out of 140 congresistas.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.database import models as db_models
from backend.database.crud.pipeline_core import save_alias
from backend.process.utils import normalize_name


def main() -> int:
    engine = create_engine(settings.DB_URL)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        rows = db.scalars(select(db_models.Congresista)).all()

        by_surname: dict[str, list[db_models.Congresista]] = {}
        for cong in rows:
            key = normalize_name(cong.last_name or "", sort_tokens=True)
            by_surname.setdefault(key, []).append(cong)

        ambiguous = {k: v for k, v in by_surname.items() if len(v) > 1}
        if ambiguous:
            logger.warning(
                f"Skipping {sum(len(v) for v in ambiguous.values())} "
                f"congresista(s) with an ambiguous (shared) surname:"
            )
            for congs in ambiguous.values():
                logger.warning("  " + ", ".join(c.full_name for c in congs))

        created = 0
        skipped_no_surname = 0
        skipped_ambiguous = 0
        skipped_existing = 0

        for cong in rows:
            key = normalize_name(cong.last_name or "", sort_tokens=True)
            if key in ambiguous:
                skipped_ambiguous += 1
                continue
            if not cong.last_name:
                skipped_no_surname += 1
                continue

            if save_alias(db, cong, cong.last_name):
                created += 1
            else:
                skipped_existing += 1

        db.commit()
        logger.info(
            f"Done. created={created} skipped_existing={skipped_existing} "
            f"skipped_ambiguous={skipped_ambiguous} "
            f"skipped_no_surname={skipped_no_surname}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
