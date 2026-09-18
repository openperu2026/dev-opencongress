from datetime import date

from sqlalchemy import select

from backend.core.constants import CHAMBER_LABEL_TO_ORG_NAME
from backend.core.enums import LegPeriod, TypeCommittee, TypeOrganization
from backend.core.parsers import LEG_PERIOD_RANGES
from backend.database.models import ChamberMembership, Membership, Organization

# UI-facing chamber options: value used in query strings, display label reused
# from the canonical Organization name so it always matches what the backend
# resolves a bill/membership's chamber to.
CHAMBER_UI_OPTIONS = [
    ("senado", CHAMBER_LABEL_TO_ORG_NAME["Senadores"]),
    ("diputados", CHAMBER_LABEL_TO_ORG_NAME["Diputados"]),
]
CHAMBER_UI_TO_ORG_NAME = dict(CHAMBER_UI_OPTIONS)
CHAMBER_ORG_NAME_TO_UI_SLUG = {v: k for k, v in CHAMBER_UI_OPTIONS}

# UI-facing period options, capped at the two bicameral-transition-relevant
# periods (not the full LegPeriod history) per product decision.
LEG_PERIOD_UI_OPTIONS = [
    ("2026-2031", "2026 - 2031", LegPeriod.PERIODO_2026_2031),
    ("2021-2026", "2021 - 2026", LegPeriod.PERIODO_2021_2026),
]

# Local dict, not an import of parsers.py's private _LEG_PERIOD_RANGE_BY_ENUM.
_LEG_PERIOD_RANGE_BY_ENUM = {p: (s, e) for p, s, e in LEG_PERIOD_RANGES}


def leg_period_date_range(leg_period_value: str) -> tuple[date, date]:
    """Full (start, end) date range for a UI period value, e.g. "2026-2031"."""
    enum_val = next(e for v, _, e in LEG_PERIOD_UI_OPTIONS if v == leg_period_value)
    return _LEG_PERIOD_RANGE_BY_ENUM[enum_val]


# 2026-2031 introduces chamber-specific ordinary-committee subtypes
# (COM_ORD_LEG/COM_ORD_NO_LEG) replacing the legacy generic COM_ORD. Legacy
# committees keep COM_ORD untouched (backend/core/enums.py), so subtype alone
# uniquely separates the two eras -- no parent_org_id scoping is needed for
# the legacy branch.
_ORDINARY_COMMITTEE_SUBTYPES_BY_PERIOD = {
    "2021-2026": [TypeCommittee.COM_ORD],
    "2026-2031": [TypeCommittee.COM_ORD_LEG, TypeCommittee.COM_ORD_NO_LEG],
}


def ordinary_committee_subtypes_for_period(leg_period_q: str) -> list:
    """Ordinary-committee org_subtype values valid for a given UI period."""
    return _ORDINARY_COMMITTEE_SUBTYPES_BY_PERIOD.get(
        leg_period_q, [TypeCommittee.COM_ORD]
    )


def committee_parent_org_ids(db, chamber_q: str) -> list[int]:
    """Chamber org_ids to scope a 2026-2031 committee lookup by parent_org_id.

    Only meaningful for the 2026-2031 period, where committees are genuinely
    parented under a specific chamber's Organization row. The legacy
    (2021-2026) period doesn't need this -- org_subtype alone (COM_ORD)
    already uniquely identifies legacy committees regardless of their parent.
    """
    chamber_names = (
        [CHAMBER_UI_TO_ORG_NAME[chamber_q]]
        if chamber_q
        else list(CHAMBER_UI_TO_ORG_NAME.values())
    )
    return db.scalars(
        select(Organization.org_id).where(Organization.org_name.in_(chamber_names))
    ).all()


def latest_org_name(db, person_id: int, org_type: TypeOrganization) -> str | None:
    return db.execute(
        select(Organization.org_name)
        .join(Membership, Membership.org_id == Organization.org_id)
        .where(
            Membership.person_id == person_id,
            Membership.org_type == org_type,
        )
        .order_by(Membership.end_date.desc(), Membership.start_date.desc())
        .limit(1)
    ).scalar_one_or_none()


def create_bancada_option(db, leg_period_q: str):
    """Bancada (parliamentary group) options -- more precise than partido
    for search purposes, since a person's voting bloc can diverge from
    their formal party (splits, expulsions, alliances)."""
    return [
        bancada_name
        for bancada_name in db.execute(
            select(Organization.org_name)
            .join(Membership, Membership.org_id == Organization.org_id)
            .where(
                Membership.org_type == TypeOrganization.BANCADA,
                Membership.leg_period == leg_period_q,
            )
            .distinct()
            .order_by(Organization.org_name.asc())
        )
        .scalars()
        .all()
    ]


def create_party_option(db, leg_period_q: str):
    return [
        party_name
        for party_name in db.execute(
            select(Organization.org_name)
            .join(Membership, Membership.org_id == Organization.org_id)
            .where(
                Membership.org_type == TypeOrganization.PARTY,
                Membership.leg_period == leg_period_q,
            )
            .distinct()
            .order_by(Organization.org_name.asc())
        )
        .scalars()
        .all()
    ]


def create_committee_option(db, leg_period_q: str):
    allowed_subtypes = _ORDINARY_COMMITTEE_SUBTYPES_BY_PERIOD.get(
        leg_period_q, [TypeCommittee.COM_ORD]
    )
    return [
        org_name
        for org_name in db.execute(
            select(Organization.org_name)
            .join(Membership, Membership.org_id == Organization.org_id)
            .where(
                Organization.org_type == TypeOrganization.COMMITTEE,
                Organization.org_subtype.in_(allowed_subtypes),
                Membership.leg_period == leg_period_q,
            )
            .distinct()
            .order_by(Organization.org_name.asc())
        )
        .scalars()
        .all()
    ]


def create_special_committee_option(db, leg_period_q: str | None = None):
    filters = [
        Organization.org_type == TypeOrganization.COMMITTEE,
        Organization.org_subtype == TypeCommittee.COM_ESP,
        Organization.org_short_name.is_not(None),
    ]
    if leg_period_q:
        filters.append(Membership.leg_period == leg_period_q)

    return [
        org_short_name
        for org_short_name in db.execute(
            select(Organization.org_short_name)
            .join(Membership, Membership.org_id == Organization.org_id)
            .where(*filters)
            .distinct()
            .order_by(Organization.org_short_name.asc())
        )
        .scalars()
        .all()
    ]


def create_region_option(db, leg_period_q: str | None = None):
    filters = [ChamberMembership.dist_electoral.is_not(None)]
    if leg_period_q:
        filters.append(ChamberMembership.leg_period == leg_period_q)

    return [
        dist_electoral
        for dist_electoral in db.execute(
            select(ChamberMembership.dist_electoral)
            .where(*filters)
            .distinct()
            .order_by(ChamberMembership.dist_electoral.asc())
        )
        .scalars()
        .all()
    ]
