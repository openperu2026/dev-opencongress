from types import SimpleNamespace

from flask import Blueprint, render_template, request
from sqlalchemy import func, or_, select
from backend.database.models import (
    Bill,
    ChamberMembership,
    Congresista,
    Membership,
    Organization,
    TypeOrganization,
)

from .processed_session import SessionProcessed

congress_bp = Blueprint("congress", __name__, template_folder="../templates")


# get the latest organizations names
def _latest_org_name(db, person_id: int, org_type: TypeOrganization) -> str | None:
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


# Get the main information of the Congressmember
def _congresista_view(db, congresista: Congresista) -> SimpleNamespace:
    party_name = _latest_org_name(db, congresista.id, TypeOrganization.PARTY)
    bancada_name = _latest_org_name(db, congresista.id, TypeOrganization.BANCADA)
    chamber_membership = db.execute(
        select(ChamberMembership)
        .where(
            ChamberMembership.person_id == congresista.id,
            ChamberMembership.org_id == 1,
        )
        .order_by(ChamberMembership.end_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    return SimpleNamespace(
        id=congresista.id,
        full_name=congresista.full_name,
        first_name=congresista.first_name,
        last_name=congresista.last_name,
        photo_url=congresista.photo_url,
        website=congresista.website,
        party_name=party_name,
        current_bancada=bancada_name,
        dist_electoral=(
            chamber_membership.dist_electoral if chamber_membership else None
        ),
        condicion=(
            chamber_membership.condicion if chamber_membership else "Not available"
        ),
        votes_in_election=(
            chamber_membership.votes_in_election if chamber_membership else 0
        ),
    )


@congress_bp.route("/congress")
def index():
    name_q = request.args.get("name_q", "").strip()
    party_q = request.args.get("party_q", "").strip()
    region_q = request.args.get("region_q", "").strip()

    congresistas = []
    filters = []

    if name_q:
        filters.append(Congresista.full_name.ilike(f"%{name_q}%"))

    if party_q:
        filters.append(
            Congresista.id.in_(
                select(Membership.person_id)
                .join(Organization, Organization.org_id == Membership.org_id)
                .where(
                    Membership.org_type.in_(
                        [TypeOrganization.PARTY, TypeOrganization.BANCADA]
                    ),
                    Organization.org_name.ilike(f"%{party_q}%"),
                )
            )
        )

    if region_q:
        filters.append(Congresista.full_name.ilike(f"%{region_q}%"))

    if filters:
        with SessionProcessed() as db:
            rows = db.execute(
                select(Congresista)
                .where(*filters)
                .order_by(Congresista.full_name.asc())
                .limit(50)
            ).scalars()
            congresistas = [_congresista_view(db, row) for row in rows]

    return render_template(
        "congress/search.html",
        name_q=name_q,
        party_q=party_q,
        region_q=region_q,
        congresistas=congresistas,
    )


@congress_bp.route("/congress/<congresista_id>")
def congress_detail(congresista_id):
    with SessionProcessed() as db:
        congresista_row = db.get(Congresista, int(congresista_id))

        if not congresista_row:
            return "Not Found", 404

        congresista = _congresista_view(db, congresista_row)

        bills_authored = [
            SimpleNamespace(
                id=bill.id,
                title=bill.title,
                summary_congreso=bill.summary_congreso,
                observations=bill.observations,
                status=bill.status,
                proponent=bill.proponent,
                author_id=bill.author_id,
                bill_approved=bill.bill_approved,
                summary_oc=bill.summary_oc,
            )
            for bill in db.execute(
                select(Bill)
                .where(Bill.author_id == congresista.id)
                .order_by(Bill.id.desc())
                .limit(5)
            ).scalars()
        ]

        bills_authored_count = db.execute(
            select(func.count())
            .select_from(Bill)
            .where(Bill.author_id == congresista.id)
        ).scalar_one()

        successful_bills_count = db.execute(
            select(func.count())
            .select_from(Bill)
            .where(
                Bill.author_id == congresista.id,
                Bill.bill_approved.is_(True),
            )
        ).scalar_one()

        memberships = (
            db.execute(
                select(
                    Membership.role,
                    Membership.start_date,
                    Membership.end_date,
                    Organization.org_name,
                    Organization.org_type,
                    Organization.org_subtype,
                )
                .join(Organization, Organization.org_id == Membership.org_id)
                .where(
                    Membership.person_id == congresista.id,
                    or_(
                        Membership.org_type == TypeOrganization.COMMITTEE,
                        Organization.org_type == TypeOrganization.COMMITTEE,
                    ),
                )
                .order_by(Membership.end_date.desc(), Membership.start_date.desc())
                .limit(8)
            )
            .mappings()
            .all()
        )

        profile_stats = {
            "assistance_rate": "45%",
            "bills_authored": bills_authored_count,
            "success_rate": "40%",
            "successful_bills": successful_bills_count,
        }

        recent_votes = [
            {
                "position": "In favor",
                "bill": "Bill N 32014",
                "description": "Vote data is not available yet. This is placeholder content for the congressperson detail view.",
            },
            {
                "position": "Against",
                "bill": "Bill N 32074",
                "description": "Vote data is not available yet. This is placeholder content for the congressperson detail view.",
            },
        ]

        return render_template(
            "congress/congress_detail.html",
            congresista=congresista,
            memberships=memberships,
            bills_authored=bills_authored,
            profile_stats=profile_stats,
            recent_votes=recent_votes,
        )
