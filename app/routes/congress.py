from types import SimpleNamespace

from flask import Blueprint, render_template, request
from sqlalchemy import select, text
from backend.database.models import Bill
from .processed_session import SessionProcessed

congress_bp = Blueprint("congress", __name__, template_folder="../templates")


@congress_bp.route("/congress")
def index():
    # q = request.args.get("q", "").strip()

    name_q = request.args.get("name_q", "").strip()
    party_q = request.args.get("party_q", "").strip()
    region_q = request.args.get("region_q", "").strip()

    congresistas = []

    filters = []
    params = {}

    if name_q:
        filters.append("lower(nombre) LIKE lower(:name_q)")
        params["name_q"] = f"%{name_q}%"

    if party_q:
        filters.append("lower(party_name) LIKE lower(:party_q)")
        params["party_q"] = f"%{party_q}%"

    if region_q:
        filters.append("lower(dist_electoral) LIKE lower(:region_q)")
        params["region_q"] = f"%{region_q}%"


    if filters:
        where_clause = " AND ".join(filters)

        query = f"""
            SELECT *
            FROM congresistas
            WHERE {where_clause}
            LIMIT 50
        """

        with SessionProcessed() as db:
            rows = db.execute(text(query), params).mappings()
            congresistas = [
                SimpleNamespace(**row, full_name=row["nombre"])
                for row in rows
            ]


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
        row = (
            db.execute(
                text("SELECT * FROM congresistas WHERE id = :id"),
                {"id": congresista_id},
            )
            .mappings()
            .first()
        )

        congresista = (
            SimpleNamespace(**row, full_name=row["nombre"]) if row is not None else None
        )
        if not congresista:
            return "Not Found", 404

        bills_authored = (
            db.execute(
                select(Bill)
                .where(Bill.author_id == congresista.id)
                .order_by(Bill.presentation_date.desc())
                .limit(5)
            )
            .scalars()
            .all()
        )

        bills_authored_count = db.execute(
            text("SELECT COUNT(*) FROM bills WHERE author_id = :person_id"),
            {"person_id": congresista.id},
        ).scalar_one()

        successful_bills_count = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM bills
                WHERE author_id = :person_id
                  AND (approved = 1 OR bill_approved = 1)
                """
            ),
            {"person_id": congresista.id},
        ).scalar_one()

        memberships = (
            db.execute(
                text(
                    """
                    SELECT
                        m.role,
                        m.start_date,
                        m.end_date,
                        o.org_name,
                        o.org_type,
                        o.comm_type
                    FROM memberships AS m
                    JOIN organizations AS o ON o.org_id = m.org_id
                    WHERE m.person_id = :person_id
                    ORDER BY m.end_date DESC, m.start_date DESC
                    LIMIT 8
                    """
                ),
                {"person_id": congresista.id},
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


@congress_bp.route("/congress/<congresista_id>/bills")
def congress_bills(congresista_id):
    with SessionProcessed() as db:
        row = (
            db.execute(
                text("SELECT * FROM congresistas WHERE id = :id"),
                {"id": congresista_id},
            )
            .mappings()
            .first()
        )

        congresista = (
            SimpleNamespace(**row, full_name=row["nombre"]) if row is not None else None
        )
        if not congresista:
            return "Not Found", 404

        bills_authored = (
            db.execute(
                select(Bill)
                .where(Bill.author_id == congresista.id)
                .order_by(Bill.presentation_date.desc())
            )
            .scalars()
            .all()
        )

        return render_template(
            "congress/congress_bill.html",
            congresista=congresista,
            bills_authored=bills_authored,
        )
