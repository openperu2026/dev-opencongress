"""Backfill known aliases for congresistas.

Populates CongresistaAlias rows from a manually curated mapping of canonical
congresista names to alternate names found in historical Congress documents.

Canonical congresistas are resolved via pipeline_core.find_congresista and
aliases are created only when the corresponding canonical congresista exists.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.database import models as db_models
from backend.database.crud import pipeline_core as crud_core

CONGRESISTA_ALIASES: dict[str, list[str]] = {
    "Gladys Margot Echaíz de Núñez Izaga": [
        "ECHAIZ DE NÚÑEZ IZAGA, GLADYS M.",
        "GLADYS M. ECHAÍZ DE NÚÑEZ IZAGA",
    ],
    "Jorge Arturo Zeballos Aponte": [
        "ZEBALLOS APONTE, JORGE",
        "JORGE ZEBALLOS APONTE",
    ],
    "Carlos Javier Zeballos Madariaga": [
        "ZEBALLOS MADARIAGA, CARLOS",
        "CARLOS ZEBALLOS MADARIAGA",
        "CARLOS ZEBALLOS MADIARIAGA",
    ],
    "Carlos Ernesto Bustamante Donayre": [
        "BUSTAMANTE DONAYRE ERNESTO",
        "ERNESTO BUSTAMANTE DONAYRE",
        "ERNESTO BUSTAMANTE",
    ],
    "Juan Carlos Martin Lizarzaburu Lizarzaburu": [
        "LIZARZABURU LIZARZABURU, JUAN C.",
        "JUAN C. LIZARZABURU LIZARZABURU",
    ],
    "Jorge Alfonso Marticorena Mendoza": [
        "MARTICORENA MENDOZA, JORGE",
        "JORGE MARTICORENA MENDOZA",
    ],
    "María de los Milagros Jackeline Jáuregui Martínez de Aguayo": [
        "JÁUREGUI MARTÍNEZ DE AGUAYO, MARIA",
        "MARÍA JAÚREGUI MARTÍNEZ DE AGUAYO",
        "MARÍA JÁUREGUI MARTÍNEZ DE AGUAYO",
        "MARÍA LUZ JÁUREGUI MARTÍNEZ DE AGUAYO",
        "MARÍA LO JÁUREGUI MARTÍNEZ DE AGUAYO",
        "MARÍA JÁUREGUI MARTINEZ DE AGUAYO",
        "MARÍA JÁUREGUI MARTÍNEZ DE AGÜAYO",
        "MARÍA JERI JÁUREGUI MARTÍNEZ DE AGUAYO",
    ],
    "Rosio Torres Salinas": [
        "ROCÍO TORRES SALINAS",
        "ROCIO TORRES SALINAS",
    ],
    "Juan Bartolomé Burgos Oliveros": [
        "GUILLERMO BARTOLOMÉ BURGOS OLIVEROS",
    ],
}


def count_aliases(db: Session) -> int | None:
    return db.scalar(select(func.count()).select_from(db_models.CongresistaAlias))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N congresistas.",
    )
    args = parser.parse_args()

    records = list(CONGRESISTA_ALIASES.items())

    if args.limit is not None:
        records = records[: args.limit]

    engine = create_engine(settings.DB_URL)
    SessionLocal = sessionmaker(bind=engine)

    processed_congresistas = 0
    aliases_processed = 0
    aliases_created = 0
    unmatched_congresistas: list[str] = []
    errors = 0

    with SessionLocal() as db:
        before_count = count_aliases(db)

        logger.info(f"Processing aliases for {len(records)} congresista(s)")

        for full_name, aliases in records:
            try:
                congresista = crud_core.find_congresista(
                    db,
                    full_name,
                )

                if congresista is None:
                    logger.warning(f"Congresista not found: {full_name!r}")
                    unmatched_congresistas.append(full_name)
                    continue

                processed_congresistas += 1

                for alias in aliases:
                    aliases_processed += 1

                    try:
                        crud_core.save_alias(
                            db=db,
                            congresista=congresista,
                            raw_name=alias,
                        )
                        aliases_created += 1
                        logger.info(
                            f"Created alias: {alias!r} -> "
                            f"{congresista.full_name!r} "
                            f"(congresista_id={congresista.id})"
                        )
                    except Exception:
                        logger.debug(
                            f"Alias already exists: {alias!r} -> "
                            f"{congresista.full_name!r}"
                        )

                db.commit()

            except Exception as exc:
                logger.exception(f"Failed processing congresista {full_name!r}: {exc}")
                db.rollback()
                errors += 1

        after_count = count_aliases(db)

    logger.info(
        f"Done. "
        f"congresistas_processed={processed_congresistas} "
        f"aliases_processed={aliases_processed} "
        f"aliases_created={aliases_created} "
        f"new_alias_rows="
        f"{after_count - before_count if after_count is not None and before_count is not None else 0} "
        f"unmatched_congresistas={len(unmatched_congresistas)} "
        f"errors={errors}"
    )

    if unmatched_congresistas:
        logger.warning(f"Unmatched congresistas: {unmatched_congresistas}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
