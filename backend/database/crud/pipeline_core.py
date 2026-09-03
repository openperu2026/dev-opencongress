from __future__ import annotations

from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session
from datetime import datetime, date
from dataclasses import dataclass
from typing import Type
from enum import Enum

from backend import TypeOrganization
from backend.process.utils import normalize_name
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


MEMBERSHIP_MODELS = {
    TypeOrganization.BANCADA.value: db_models.BancadaMembership,
    TypeOrganization.PARTY.value: db_models.PartyMembership,
    TypeOrganization.CHAMBER.value: db_models.ChamberMembership,
    TypeOrganization.COMMITTEE.value: db_models.CommitteeMembership,
    TypeOrganization.ADMINISTRATIVE.value: db_models.AdminMembership,
}


def _enum_value(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _given_name_first(name: str) -> str:
    """
    Vote-roster/roll `full_name` values are transcribed as
    "SURNAME(S), GIVEN NAME(S)" (see system_prompt_bills.md Section 2b),
    but `Congresista.full_name` is stored "GIVEN NAME(S) SURNAME(S)".
    Jaro-Winkler is order-sensitive, so comparing the two as-is scores a
    correct match as low as ~0.70-0.76 -- well under the 0.9 threshold --
    purely because the words are reversed, not because the name is wrong.
    Reordering on the comma before the fuzzy comparison fixed 91% of the
    production name-match failure rate measured on 2026-08-18 (6.87% ->
    0.63% occurrence-weighted, verified against the full 75,905-occurrence
    dataset). Names without a comma are returned unchanged.
    """
    if "," not in name:
        return name
    surname, given = name.split(",", 1)
    return f"{given.strip()} {surname.strip()}"


def find_congresista(
    db: Session,
    name: str,
    website: str | None = None,
    threshold: float = 0.9,
) -> db_models.Congresista | None:
    """
    Find a congressperson using website, aliases, or fuzzy name matching.

    Matching is attempted in the following order:

    1. Website exact match.
    2. Known alias exact match.
    3. Canonical full-name fuzzy match (Jaro-Winkler), after reordering a
       "SURNAME, GIVEN" input to "GIVEN SURNAME" (see `_given_name_first`).

    Args:
        db (Session): Active SQLAlchemy database session.
        name (str): Name of the congressperson.
        website (str | None, optional): Congressperson website URL.
        threshold (float, optional): Minimum Jaro-Winkler similarity.
            Defaults to 0.9.

    Returns:
        db_models.Congresista | None: The matching congressperson if found;
        otherwise, None.
    """

    # 1. Website
    if website:
        by_web = db.scalar(
            select(db_models.Congresista).where(
                db_models.Congresista.website == website.strip()
            )
        )

        if by_web is not None:
            return by_web

    normalized_name = normalize_name(name, sort_tokens=True)

    if not normalized_name:
        return None

    # Known alias
    by_alias = db.scalar(
        select(db_models.Congresista)
        .join(db_models.CongresistaAlias)
        .where(db_models.CongresistaAlias.name == normalized_name)
    )

    if by_alias is not None:
        return by_alias

    # Fuzzy canonical name (preserve word order for Jaro-Winkler comparison,
    # after reordering "SURNAME, GIVEN" input to match full_name's own
    # "GIVEN SURNAME" order -- see _given_name_first)
    normalized_name_unsorted = normalize_name(
        _given_name_first(name), sort_tokens=False
    )
    score = func.jarowinkler(
        func.unaccent(func.lower(db_models.Congresista.full_name)),
        func.unaccent(normalized_name_unsorted),
    )

    stmt = (
        select(db_models.Congresista)
        .where(score >= threshold)
        .order_by(
            score.desc(),
            db_models.Congresista.id.asc(),
        )
        .limit(1)
    )

    return db.scalar(stmt)


def save_alias(
    db: Session,
    congresista: db_models.Congresista,
    raw_name: str,
) -> bool:
    """Create an alias if it does not already exist.

    Returns:
        True if a new alias was created, otherwise False.
    """
    normalized = normalize_name(raw_name)

    if not normalized:
        return False

    exists = db.scalar(
        select(db_models.CongresistaAlias.id).where(
            db_models.CongresistaAlias.congresista_id == congresista.id,
            db_models.CongresistaAlias.name == normalized,
        )
    )

    if exists is None:
        db.add(
            db_models.CongresistaAlias(
                congresista_id=congresista.id,
                name=normalized,
            )
        )
        return True

    return False


def find_organization(
    db: Session,
    org_name: str,
    org_type: TypeOrganization | str,
    threshold: float = 0.9,
    parent_org_id: int | None = None,
) -> db_models.Organization | None:
    """
    Find the closest organization by fuzzy name match and organization type.

    parent_org_id: optionally scope the match to organizations under a specific
    parent. Needed because Organization.org_uniq is (org_name, org_type,
    parent_org_id) — two orgs can share a name+type under different parents
    (e.g. a same-named committee under each chamber). Omit (or pass None) to
    preserve prior unscoped behavior; None is never used to mean "match rows
    with a NULL parent" since no two same-name/same-type orgs legitimately
    share a NULL parent (top-level chambers and parties are each unique).
    """

    if isinstance(org_type, str):
        org_type = TypeOrganization(org_type)

    normalized_name = org_name.strip().lower()

    score = func.jarowinkler(
        func.unaccent(func.lower(db_models.Organization.org_name)),
        func.unaccent(normalized_name),
    )

    filters = [
        db_models.Organization.org_type == org_type,
        score >= threshold,
    ]
    if parent_org_id is not None:
        filters.append(db_models.Organization.parent_org_id == parent_org_id)

    stmt = (
        select(db_models.Organization)
        .where(*filters)
        .order_by(
            score.desc(),
            db_models.Organization.org_id.asc(),
        )
        .limit(1)
    )

    return db.scalar(stmt)


def find_active_bancada_for_person(
    db: Session, person_id: int, at_date: date | datetime
) -> db_models.Organization | None:
    if isinstance(at_date, datetime):
        at_date = at_date.date()

    return db.scalar(
        select(db_models.Organization)
        .join(
            db_models.Membership,
            db_models.Membership.org_id == db_models.Organization.org_id,
        )
        .where(
            db_models.Membership.person_id == person_id,
            db_models.Membership.org_type == TypeOrganization.BANCADA.value,
            db_models.Membership.start_date <= at_date,
            or_(
                db_models.Membership.end_date.is_(None),
                db_models.Membership.end_date >= at_date,
            ),
        )
        .order_by(db_models.Membership.start_date.desc())
        .limit(1)
    )


def _upsert_model(
    db: Session,
    *,
    existing: db_models.Congresista
    | db_models.Organization
    | db_models.Membership
    | db_models.Ley,
    model: Type[db_models.Congresista]
    | Type[db_models.Organization]
    | Type[db_models.Membership]
    | Type[db_models.Ley],
    payload: dict,
) -> (
    db_models.Congresista
    | db_models.Organization
    | db_models.Membership
    | db_models.Ley
):
    if existing is None:
        obj = model(**payload)
        db.add(obj)
        db.flush()
        return obj

    # Coalesce, don't blindly overwrite: a matched source can legitimately
    # carry less data than what's already stored (e.g. the 2026-2031
    # chamber congresista scrape has no dni/gender/first_name/last_name at
    # all) -- a None in the payload must never clobber an existing value.
    # Found 2026-09: this exact gap silently wiped dni/gender/first_name/
    # last_name for every reelected congresista matched against their
    # pre-existing legacy row.
    for key, value in payload.items():
        if value is not None:
            setattr(existing, key, value)

    db.flush()
    return existing


def upsert_congresista(
    db: Session, schema: schema.Congresista
) -> db_models.Congresista:
    existing = find_congresista(db, schema.full_name, schema.website)
    payload = schema.model_dump()

    return _upsert_model(
        db,
        existing=existing,
        model=db_models.Congresista,
        payload=payload,
    )


def upsert_organization(
    db: Session, schema: schema.Organization
) -> db_models.Organization:
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

    payload["org_type"] = _enum_value(payload["org_type"])
    if payload.get("org_subtype") is not None:
        payload["org_subtype"] = _enum_value(payload["org_subtype"])

    # Scope the existing-row check by parent_org_id, matching the real
    # org_uniq constraint (org_name, org_type, parent_org_id) — without this,
    # two same-named orgs under different parents (e.g. a same-named
    # committee under each chamber) would collide and silently overwrite
    # each other's parent_org_id.
    existing = find_organization(
        db, schema.org_name, schema.org_type, parent_org_id=parent_id
    )

    return _upsert_model(
        db,
        existing=existing,
        model=db_models.Organization,
        payload=payload,
    )


def membership_exists(
    db: Session,
    *,
    person_id: int,
    org_id: int,
    leg_period: str | Enum,
    org_type: str | TypeOrganization,
) -> bool:
    """True if ANY Membership row already exists for this (person, org,
    leg_period, org_type), regardless of start_date/end_date/role -- unlike
    upsert_membership's own existing-row lookup, which is keyed on the
    exact start_date/end_date/role too (so it can't answer "has this
    person ever had this membership before", only "does this exact
    date/role combination already exist").
    """
    return (
        db.scalars(
            select(db_models.Membership.id).where(
                db_models.Membership.person_id == person_id,
                db_models.Membership.org_id == org_id,
                db_models.Membership.leg_period == _enum_value(leg_period),
                db_models.Membership.org_type == _enum_value(org_type),
            )
        ).first()
        is not None
    )


def upsert_membership(
    db: Session,
    *,
    person_id: int,
    org_id: int,
    leg_period: str,
    org_type: str | TypeOrganization,
    role: str,
    start_date: date,
    end_date: date,
    extra_fields: dict | None = None,
) -> db_models.Membership:
    org_type_value = _enum_value(org_type)
    role_value = _enum_value(role)
    leg_period_value = _enum_value(leg_period)
    model = MEMBERSHIP_MODELS[org_type_value]

    payload = {
        "person_id": person_id,
        "org_id": org_id,
        "leg_period": leg_period_value,
        "org_type": org_type_value,
        "role": role_value,
        "start_date": start_date,
        "end_date": end_date,
    }

    if extra_fields:
        payload.update(extra_fields)

    existing = db.scalars(
        select(db_models.Membership).where(
            db_models.Membership.person_id == person_id,
            db_models.Membership.org_id == org_id,
            db_models.Membership.leg_period == leg_period_value,
            db_models.Membership.org_type == org_type_value,
            db_models.Membership.role == role_value,
            db_models.Membership.start_date == start_date,
            db_models.Membership.end_date == end_date,
        )
    ).first()

    return _upsert_model(
        db,
        existing=existing,
        model=model,
        payload=payload,
    )


def upsert_ley(db: Session, schema: schema.Ley) -> db_models.Ley:
    payload = {
        "id": schema.id,
        "title": schema.title,
        "bill_id": schema.bill_id,
    }

    existing = db.get(db_models.Ley, schema.id)

    return _upsert_model(db, existing=existing, model=db_models.Ley, payload=payload)


def upsert_scraper_run(db: Session, scraper_name: str, stats: ScraperStats):
    obj = ScraperRun(
        scraper_name=scraper_name,
        start_time=stats.start_time,
        end_time=stats.end_time,
        scraped_rows=stats.scrapped,
    )

    db.add(obj)
    db.commit()
