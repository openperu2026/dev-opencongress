from math import ceil

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.core.enums import TypeCommittee, TypeOrganization
from backend.database.models import (
    Bill,
    ChamberMembership,
    Congresista,
    Membership,
    Organization,
)


def _latest_party_name(db: Session, congresista_id: int) -> str | None:
    return db.scalar(
        select(Organization.org_name)
        .join(Membership, Membership.org_id == Organization.org_id)
        .where(
            Membership.person_id == congresista_id,
            Membership.org_type == TypeOrganization.PARTY,
        )
        .order_by(desc(Membership.end_date), desc(Membership.start_date))
        .limit(1)
    )


def _latest_chamber_membership(
    db: Session,
    congresista_id: int,
) -> ChamberMembership | None:
    return db.execute(
        select(ChamberMembership)
        .where(ChamberMembership.person_id == congresista_id)
        .order_by(desc(ChamberMembership.end_date), desc(ChamberMembership.start_date))
        .limit(1)
    ).scalar_one_or_none()


def _text_search(column, value: str):
    return func.unaccent(func.lower(column)).like(
        func.unaccent(func.lower(f"%{value}%"))
    )


def _bill_metrics(db: Session, congresista_id: int) -> dict:
    bills_authored_count = db.execute(
        select(func.count()).select_from(Bill).where(Bill.author_id == congresista_id)
    ).scalar_one()

    successful_bills_count = db.execute(
        select(func.count())
        .select_from(Bill)
        .where(
            Bill.author_id == congresista_id,
            Bill.bill_approved.is_(True),
        )
    ).scalar_one()

    approval_rate = (
        round(100 * (successful_bills_count / bills_authored_count), 1)
        if bills_authored_count
        else 0
    )

    return {
        "proyectos_de_ley_presentados": bills_authored_count,
        "tasa_de_aprobacion_de_proyectos": approval_rate,
    }


def _congress_member_to_dict(db: Session, congresista: Congresista) -> dict:
    chamber_membership = _latest_chamber_membership(db, congresista.id)

    return {
        "id": congresista.id,
        "full_name": congresista.full_name,
        "first_name": congresista.first_name,
        "last_name": congresista.last_name,
        "photo_url": congresista.photo_url,
        "website": congresista.website,
        "party_name": _latest_party_name(db, congresista.id),
        "region": (chamber_membership.dist_electoral if chamber_membership else None),
        "condition": chamber_membership.condicion if chamber_membership else None,
        "votes_in_election": (
            chamber_membership.votes_in_election if chamber_membership else None
        ),
        "metrics": _bill_metrics(db, congresista.id),
    }


def search_congress_members(db: Session, args: dict) -> dict:
    """Search congress members for the public API list endpoint."""
    page = args["page"]
    per_page = args["per_page"]

    stmt = select(Congresista).order_by(Congresista.full_name.asc())
    filters = []

    if args.get("name"):
        filters.append(_text_search(Congresista.full_name, args["name"]))

    if args.get("party"):
        filters.append(
            Congresista.id.in_(
                select(Membership.person_id)
                .join(Organization, Organization.org_id == Membership.org_id)
                .where(
                    Membership.org_type == TypeOrganization.PARTY,
                    _text_search(Organization.org_name, args["party"]),
                )
            )
        )

    if args.get("region"):
        filters.append(
            Congresista.id.in_(
                select(ChamberMembership.person_id)
                .where(_text_search(ChamberMembership.dist_electoral, args["region"]))
                .distinct()
            )
        )

    if args.get("condition"):
        filters.append(
            Congresista.id.in_(
                select(ChamberMembership.person_id)
                .where(_text_search(ChamberMembership.condicion, args["condition"]))
                .distinct()
            )
        )

    if args.get("committee"):
        filters.append(
            Congresista.id.in_(
                select(Membership.person_id)
                .join(Organization, Organization.org_id == Membership.org_id)
                .where(
                    Membership.org_type == TypeOrganization.COMMITTEE,
                    Organization.org_subtype == TypeCommittee.COM_ORD,
                    _text_search(Organization.org_name, args["committee"]),
                )
            )
        )

    if args.get("special_committee"):
        filters.append(
            Congresista.id.in_(
                select(Membership.person_id)
                .join(Organization, Organization.org_id == Membership.org_id)
                .where(
                    Membership.org_type == TypeOrganization.COMMITTEE,
                    Organization.org_subtype == TypeCommittee.COM_ESP,
                    _text_search(
                        Organization.org_short_name,
                        args["special_committee"],
                    ),
                )
            )
        )

    if filters:
        stmt = stmt.where(*filters)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    rows = (
        db.execute(stmt.offset((page - 1) * per_page).limit(per_page)).scalars().all()
    )

    return {
        "items": [_congress_member_to_dict(db, row) for row in rows],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": ceil(total / per_page) if total else 0,
        },
    }
