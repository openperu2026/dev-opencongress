"""Backfill historic Bancada memberships for the 2021-2026 legislative period.

Reads data/congresistas_2021_2026_FINAL.json and creates BancadaMembership rows
for every congresista/bancada period found in it. Congresistas are resolved via
pipeline_core.find_congresista and are never created if missing. Bancada
organizations are resolved via pipeline_core.find_organization, creating a new
one (parented under "Cámara de Diputados") only if no fuzzy match is found.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend import LegPeriod, RoleOrganization, TypeOrganization
from backend.config import settings
from backend.database import models as db_models
from backend.database.crud import pipeline_core as crud_core
from backend.process import schema

DEFAULT_JSON_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "congresistas_2021_2026_FINAL.json"
)
LEG_PERIOD = LegPeriod.PERIODO_2021_2026.value
PARENT_ORG_NAME = "Cámara de Diputados"


def load_records(json_path: Path) -> list[dict]:
    with open(json_path, encoding="utf-8") as file:
        return json.load(file)


def build_full_name(rec: dict) -> str:
    return f"{rec['nombre']} {rec['apellido']}".strip()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%d/%m/%Y").date()


def resolve_bancada(
    db: Session, name: str, cache: dict[str, tuple[db_models.Organization, bool]]
) -> db_models.Organization:
    if name in cache:
        return cache[name][0]

    existing = crud_core.find_organization(db, name, TypeOrganization.BANCADA)
    if existing is not None:
        cache[name] = (existing, False)
        return existing

    org_schema = schema.Organization(
        org_name=name,
        org_type=TypeOrganization.BANCADA,
        parent_org_name=PARENT_ORG_NAME,
        parent_org_type=TypeOrganization.CHAMBER,
    )
    org = crud_core.upsert_organization(db, org_schema)
    cache[name] = (org, True)
    logger.info(f"Created new Bancada organization: {name!r} (org_id={org.org_id})")
    return org


def count_bancada_memberships(db: Session) -> int | None:
    return db.scalar(
        select(func.count())
        .select_from(db_models.Membership)
        .where(
            db_models.Membership.org_type == TypeOrganization.BANCADA,
            db_models.Membership.leg_period == LEG_PERIOD,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-path", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    records = load_records(args.json_path)
    if args.limit:
        records = records[: args.limit]

    engine = create_engine(settings.DB_URL)
    SessionLocal = sessionmaker(bind=engine)

    org_cache: dict[str, tuple[db_models.Organization, bool]] = {}
    unmatched_congresistas: list[tuple[str, str, str | None]] = []
    processed = 0
    errors = 0

    with SessionLocal() as db:
        chamber_org = crud_core.find_organization(
            db, PARENT_ORG_NAME, TypeOrganization.CHAMBER
        )
        if chamber_org is None:
            logger.error(
                f"Parent chamber organization {PARENT_ORG_NAME!r} not found; aborting."
            )
            return 1

        before_count = count_bancada_memberships(db)
        logger.info(f"Processing {len(records)} congresista record(s)")

        for rec in records:
            full_name = build_full_name(rec)
            website = rec.get("website") or None

            congresista = crud_core.find_congresista(db, full_name, website)
            if congresista is None:
                logger.warning(
                    f"No matching congresista for id={rec['id']} name={full_name!r} "
                    f"website={website!r}"
                )
                unmatched_congresistas.append((rec["id"], full_name, website))
                continue

            try:
                for entry in rec.get("bancada", []):
                    org = resolve_bancada(db, entry["name"], org_cache)
                    start_date = parse_date(entry["periodo"]["inicio"])
                    end_date = parse_date(entry["periodo"]["fin"])

                    crud_core.upsert_membership(
                        db,
                        person_id=congresista.id,
                        org_id=org.org_id,
                        leg_period=LEG_PERIOD,
                        org_type=TypeOrganization.BANCADA,
                        role=RoleOrganization.MIEMBRO,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    processed += 1

                db.commit()
            except Exception as exc:
                logger.exception(
                    f"Failed for congresista id={rec['id']} ({full_name}): {exc}"
                )
                db.rollback()
                errors += 1

        after_count = count_bancada_memberships(db)
        new_orgs = [name for name, (_, created) in org_cache.items() if created]

    logger.info(
        f"Done. bancada_entries_processed={processed} "
        f"new_membership_rows={after_count - before_count if after_count is not None and before_count is not None else 0} "
        f"new_organizations={len(new_orgs)} "
        f"unmatched_congresistas={len(unmatched_congresistas)} "
        f"errors={errors}"
    )
    if new_orgs:
        logger.info(f"New Bancada organizations created: {new_orgs}")
    if unmatched_congresistas:
        logger.warning(f"Unmatched congresistas: {unmatched_congresistas}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
