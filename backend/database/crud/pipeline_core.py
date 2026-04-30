from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from datetime import datetime
from dataclasses import dataclass

from backend import TypeOrganization
from backend.database import models as db_models
from backend.process import schema
from backend.database.raw_models import ScraperRun


@dataclass
class ProcessStats:
    processed: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass
class ScraperStats:
    start_time: datetime
    end_time: datetime
    scrapped: int = 0


def _normalize_leg_year(leg_year) -> str:
    return str(leg_year.value) if hasattr(leg_year, "value") else str(leg_year)


def find_congresista(
    db: Session, name: str, website: str | None = None
) -> db_models.Congresista | None:
    if website:
        by_web = db.scalar(
            select(db_models.Congresista).where(
                db_models.Congresista.website == website
            )
        )
        if by_web is not None:
            return by_web
    return db.scalar(
        select(db_models.Congresista).where(
            db_models.Congresista.full_name == name,
        )
    )


def find_organization(
    db: Session, org_name: str, org_type: TypeOrganization
) -> db_models.Organization | None:
    return db.scalar(
        select(db_models.Organization).where(
            db_models.Organization.org_name == org_name,
            db_models.Organization.org_type == org_type.value,
        )
    )


def upsert_congresista(
    db: Session, schema: schema.Congresista
) -> db_models.Congresista:
    existing = find_congresista(db, schema.full_name, schema.website)
    payload = schema.model_dump()

    if existing is None:
        obj = db_models.Congresista(**payload)
        db.add(obj)
        db.flush()
        return obj

    for key, value in payload.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def upsert_organization(
    db: Session, schema: schema.Organization
) -> db_models.Organization:
    existing = find_organization(db, schema.org_name, schema.org_type)
    payload = schema.model_dump()

    parent_name = payload.pop("parent_org_name", None)
    parent_type = payload.pop("parent_org_type", None)

    parent_id = None
    if parent_name and parent_type:
        parent = find_organization(
            db,
            org_name=parent_name,
            org_type=parent_type,
        )

        if parent is None:
            raise ValueError(
                f"Parent organization not found: {parent_name} ({parent_type})"
            )

        parent_id = parent.org_id

    payload["parent_org_id"] = parent_id

    if existing is None:
        if existing is None:
            obj = db_models.Organization(**payload)
            db.add(obj)
            db.flush()
            return obj

    for key, value in payload.items():
        setattr(existing, key, value)

    db.flush()
    return existing


def upsert_membership(
    db: Session, *, person_id: int, org_id: int, role, start_date, end_date
) -> db_models.Membership:
    existing = (
        db.query(db_models.Membership)
        .filter(
            db_models.Membership.person_id == person_id,
            db_models.Membership.org_id == org_id,
            db_models.Membership.role == role,
            db_models.Membership.start_date == start_date,
            db_models.Membership.end_date == end_date,
        )
        .first()
    )
    if existing is not None:
        return existing

    obj = db_models.Membership(
        person_id=person_id,
        org_id=org_id,
        role=role,
        start_date=start_date,
        end_date=end_date,
    )
    db.add(obj)
    db.flush()
    return obj


# def upsert_bancada(db: Session, leg_year, bancada_name: str) -> db_models.Bancada:
#     normalized_leg_year = _normalize_leg_year(leg_year)
#     existing = (
#         db.query(db_models.Bancada)
#         .filter(
#             db_models.Bancada.leg_year == normalized_leg_year,
#             func.lower(db_models.Bancada.bancada_name) == bancada_name.lower(),
#         )
#         .first()
#     )
#     if existing is not None:
#         return existing

#     obj = db_models.Bancada(leg_year=normalized_leg_year, bancada_name=bancada_name)
#     db.add(obj)
#     db.flush()
#     return obj


# def upsert_bancadas_bulk(
#     db: Session, rows: list[tuple]
# ) -> tuple[dict[tuple[str, str], db_models.Bancada], int, int]:
#     """
#     Batch upsert bancadas.

#     Returns:
#         - index: {(leg_year_str, bancada_name_lower): Bancada}
#         - inserted_count
#         - existing_count
#     """
#     if not rows:
#         return {}, 0, 0

#     deduped: dict[tuple[str, str], str] = {}
#     for leg_year, bancada_name in rows:
#         normalized_leg_year = _normalize_leg_year(leg_year)
#         key = (normalized_leg_year, bancada_name.lower())
#         deduped.setdefault(key, bancada_name)

#     years = {key[0] for key in deduped}
#     names_lower = {key[1] for key in deduped}

#     existing = (
#         db.query(db_models.Bancada)
#         .filter(
#             db_models.Bancada.leg_year.in_(years),
#             func.lower(db_models.Bancada.bancada_name).in_(names_lower),
#         )
#         .all()
#     )
#     index: dict[tuple[str, str], db_models.Bancada] = {
#         (_normalize_leg_year(row.leg_year), row.bancada_name.lower()): row
#         for row in existing
#     }

#     to_insert: list[db_models.Bancada] = []
#     existing_count = 0
#     for key, original_name in deduped.items():
#         if key in index:
#             existing_count += 1
#             continue
#         to_insert.append(db_models.Bancada(leg_year=key[0], bancada_name=original_name))

#     if to_insert:
#         db.add_all(to_insert)
#         db.flush()
#         for row in to_insert:
#             index[(_normalize_leg_year(row.leg_year), row.bancada_name.lower())] = row

#     return index, len(to_insert), existing_count


# def upsert_bancada_membership(
#     db: Session, *, leg_year, person_id: int, bancada_id: int
# ) -> db_models.BancadaMembership:
#     normalized_leg_year = _normalize_leg_year(leg_year)
#     existing = (
#         db.query(db_models.BancadaMembership)
#         .filter(
#             db_models.BancadaMembership.leg_year == normalized_leg_year,
#             db_models.BancadaMembership.person_id == person_id,
#             db_models.BancadaMembership.bancada_id == bancada_id,
#         )
#         .first()
#     )
#     if existing is not None:
#         return existing

#     obj = db_models.BancadaMembership(
#         leg_year=normalized_leg_year,
#         person_id=person_id,
#         bancada_id=bancada_id,
#     )
#     db.add(obj)
#     db.flush()
#     return obj


# def upsert_bancada_memberships_bulk(db: Session, rows: list[tuple]) -> int:
#     """
#     Batch insert missing bancada memberships.

#     Args:
#         rows: [(leg_year, person_id, bancada_id), ...]

#     Returns:
#         inserted_count
#     """
#     if not rows:
#         return 0

#     keys = {
#         (_normalize_leg_year(leg_year), person_id, bancada_id)
#         for leg_year, person_id, bancada_id in rows
#     }
#     if not keys:
#         return 0

#     existing_keys = set(
#         db.query(
#             db_models.BancadaMembership.leg_year,
#             db_models.BancadaMembership.person_id,
#             db_models.BancadaMembership.bancada_id,
#         )
#         .filter(
#             tuple_(
#                 db_models.BancadaMembership.leg_year,
#                 db_models.BancadaMembership.person_id,
#                 db_models.BancadaMembership.bancada_id,
#             ).in_(keys)
#         )
#         .all()
#     )

#     to_insert = [
#         db_models.BancadaMembership(
#             leg_year=leg_year,
#             person_id=person_id,
#             bancada_id=bancada_id,
#         )
#         for leg_year, person_id, bancada_id in keys
#         if (leg_year, person_id, bancada_id) not in existing_keys
#     ]
#     if not to_insert:
#         return 0

#     db.add_all(to_insert)
#     db.flush()
#     return len(to_insert)


def upsert_ley(db: Session, schema: schema.Ley) -> db_models.Ley:
    payload = {
        "id": schema.id,
        "title": schema.title,
        "bill_id": schema.bill_id,
    }

    existing = db.get(db_models.Ley, schema.id)
    if existing is None:
        obj = db_models.Ley(**payload)
        db.add(obj)
        db.flush()
        return obj

    for key, value in payload.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def upsert_scraper_runs(raw_db: Session, runs: dict[str, ScraperStats]):
    runs_list = [
        ScraperRun(scraper, stats.start_time, stats.end_time, stats.scrapped)
        for scraper, stats in runs.items()
    ]
    raw_db.add_all(runs_list)
    raw_db.flush()
    return len(runs_list)
