from math import ceil
from types import SimpleNamespace
from datetime import date
from flask import (
    Blueprint,
    Response,
    abort,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import gettext as _
from sqlalchemy import case, func, or_, select
from backend.core.enums import TypeCommittee, TypeOrganization
from backend.database.models import (
    Bill,
    ChamberMembership,
    BillOrganization,
    Congresista,
    Membership,
    Organization,
)


from .utils import (
    CHAMBER_ORG_NAME_TO_UI_SLUG,
    CHAMBER_UI_TO_ORG_NAME,
    LEG_PERIOD_UI_OPTIONS,
    create_committee_option,
    create_party_option,
    create_region_option,
    create_special_committee_option,
    latest_org_name,
    leg_period_date_range,
    ordinary_committee_subtypes_for_period,
)
from .processed_session import SessionProcessed

congress_bp = Blueprint("congress", __name__, template_folder="../templates")


def _batch_congresista_extras(db, person_ids: list[int], leg_period_q: str):
    """Batch-resolve each person's latest party name and their
    leg_period-scoped chamber membership in 2 queries total, instead of the
    previous 2-per-row N+1 pattern.

    Returns (party_names: {person_id: name}, chamber_rows: {person_id: row}).
    """
    if not person_ids:
        return {}, {}

    latest_party = (
        select(
            Membership.person_id,
            Organization.org_name.label("party_name"),
            func.row_number()
            .over(
                partition_by=Membership.person_id,
                order_by=(Membership.end_date.desc(), Membership.start_date.desc()),
            )
            .label("rn"),
        )
        .join(Organization, Organization.org_id == Membership.org_id)
        .where(
            Membership.person_id.in_(person_ids),
            Membership.org_type == TypeOrganization.PARTY,
        )
        .subquery()
    )
    party_names = dict(
        db.execute(
            select(latest_party.c.person_id, latest_party.c.party_name).where(
                latest_party.c.rn == 1
            )
        ).all()
    )

    latest_chamber = (
        select(
            ChamberMembership.person_id,
            ChamberMembership.condicion,
            ChamberMembership.dist_electoral,
            ChamberMembership.votes_in_election,
            Organization.org_name.label("chamber_org_name"),
            func.row_number()
            .over(
                partition_by=ChamberMembership.person_id,
                order_by=(
                    ChamberMembership.end_date.desc(),
                    ChamberMembership.start_date.desc(),
                ),
            )
            .label("rn"),
        )
        .join(Organization, Organization.org_id == ChamberMembership.org_id)
        .where(
            ChamberMembership.person_id.in_(person_ids),
            ChamberMembership.leg_period == leg_period_q,
        )
        .subquery()
    )
    chamber_rows = {
        row.person_id: row
        for row in db.execute(
            select(latest_chamber).where(latest_chamber.c.rn == 1)
        ).all()
    }

    return party_names, chamber_rows


def _congresista_view_from_batch(
    congresista: Congresista, party_name, chamber_row
) -> SimpleNamespace:
    return SimpleNamespace(
        id=congresista.id,
        full_name=congresista.full_name,
        first_name=congresista.first_name,
        last_name=congresista.last_name,
        photo_url=congresista.photo_url,
        website=congresista.website,
        party_name=party_name,
        dist_electoral=chamber_row.dist_electoral if chamber_row else None,
        condicion=chamber_row.condicion if chamber_row else _("No disponible"),
        votes_in_election=chamber_row.votes_in_election if chamber_row else 0,
        chamber_slug=(
            CHAMBER_ORG_NAME_TO_UI_SLUG.get(chamber_row.chamber_org_name)
            if chamber_row
            else None
        ),
    )


# Get the main information of the Congressmember, regardless of period --
# used only by the detail page, which shows one person's most recent
# standing rather than a period-filtered search result.
def _congresista_view(db, congresista: Congresista) -> SimpleNamespace:
    party_name = latest_org_name(db, congresista.id, TypeOrganization.PARTY)
    chamber_membership = db.execute(
        select(ChamberMembership)
        .where(ChamberMembership.person_id == congresista.id)
        .order_by(
            ChamberMembership.end_date.desc(), ChamberMembership.start_date.desc()
        )
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
        dist_electoral=(
            chamber_membership.dist_electoral if chamber_membership else None
        ),
        condicion=(
            chamber_membership.condicion if chamber_membership else _("No disponible")
        ),
        votes_in_election=(
            chamber_membership.votes_in_election if chamber_membership else 0
        ),
        chamber_slug=(
            CHAMBER_ORG_NAME_TO_UI_SLUG.get(
                db.execute(
                    select(Organization.org_name).where(
                        Organization.org_id == chamber_membership.org_id
                    )
                ).scalar_one_or_none()
            )
            if chamber_membership
            else None
        ),
    )


def _congresista_period_data(db, congresista_id: int) -> dict[str, SimpleNamespace]:
    """One entry per leg_period this person has a ChamberMembership for,
    each carrying that period's chamber/party/district/condicion/votes --
    lets the detail page show a re-elected person's other term instead of
    only ever showing their most recent one."""
    chamber_rows = db.execute(
        select(
            ChamberMembership.leg_period,
            ChamberMembership.condicion,
            ChamberMembership.dist_electoral,
            ChamberMembership.votes_in_election,
            Organization.org_name.label("chamber_org_name"),
        )
        .join(Organization, Organization.org_id == ChamberMembership.org_id)
        .where(ChamberMembership.person_id == congresista_id)
        .order_by(
            ChamberMembership.end_date.desc(), ChamberMembership.start_date.desc()
        )
    ).all()

    party_by_period: dict[str, str] = {}
    for row in db.execute(
        select(Membership.leg_period, Organization.org_name)
        .join(Organization, Organization.org_id == Membership.org_id)
        .where(
            Membership.person_id == congresista_id,
            Membership.org_type == TypeOrganization.PARTY,
        )
        .order_by(Membership.end_date.desc(), Membership.start_date.desc())
    ).all():
        party_by_period.setdefault(row.leg_period, row.org_name)

    by_period: dict[str, SimpleNamespace] = {}
    for row in chamber_rows:
        # chamber_rows is already ordered most-recent-first, so setdefault
        # keeps only the latest row within a period that has more than one
        # (e.g. a mid-term district change).
        by_period.setdefault(
            row.leg_period,
            SimpleNamespace(
                chamber_slug=CHAMBER_ORG_NAME_TO_UI_SLUG.get(row.chamber_org_name),
                party_name=party_by_period.get(row.leg_period),
                dist_electoral=row.dist_electoral,
                condicion=row.condicion,
                votes_in_election=row.votes_in_election,
            ),
        )
    return by_period


def _photo_mimetype(photo_bytes: bytes) -> str:
    if photo_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if photo_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if photo_bytes.startswith(b"RIFF") and photo_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


@congress_bp.route("/congress")
def index():
    name_q = request.args.get("name_q", "").strip()
    party_q = request.args.get("party_q", "").strip()
    region_q = request.args.get("region_q", "").strip()
    commission_q = request.args.get("commission_q", "").strip()
    special_committee_q = request.args.get("special_committee_q", "").strip()
    chamber_q = request.args.get("chamber_q", "").strip()
    leg_period_q = request.args.get("leg_period_q", "").strip()
    page = request.args.get("page", 1, type=int)
    page = page if page and page > 0 else 1
    per_page = 50

    _allowed_chamber = {"", "senado", "diputados"}
    if chamber_q not in _allowed_chamber:
        chamber_q = ""
    _allowed_leg_period = {v for v, _, _ in LEG_PERIOD_UI_OPTIONS}
    if leg_period_q not in _allowed_leg_period:
        leg_period_q = "2026-2031"
    leg_period_display = next(
        label for v, label, _ in LEG_PERIOD_UI_OPTIONS if v == leg_period_q
    )
    chamber_display = CHAMBER_UI_TO_ORG_NAME.get(chamber_q)

    congresistas = []
    filters = []
    party_options = []
    region_options = []
    committee_options = []
    special_committee_options = []
    total_count = 0
    results_start = 0
    results_end = 0
    pagination_pages = []

    search_params = dict(
        name_q=name_q,
        party_q=party_q,
        region_q=region_q,
        commission_q=commission_q,
        special_committee_q=special_committee_q,
        chamber_q=chamber_q,
        leg_period_q=leg_period_q,
    )

    # Pre-built so the template just looks these up -- Jinja has no
    # equivalent to Python's {**dict, "k": v} merge-literal syntax, so the
    # per-tab param override has to happen here, not in the template.
    period_tab_urls = {
        value: url_for("congress.index", **{**search_params, "leg_period_q": value})
        for value, _label, _enum in LEG_PERIOD_UI_OPTIONS
    }
    chamber_tab_urls = {
        value: url_for("congress.index", **{**search_params, "chamber_q": value})
        for value in [""] + list(CHAMBER_UI_TO_ORG_NAME.keys())
    }

    if name_q:
        filters.append(
            func.unaccent(func.lower(Congresista.full_name)).like(
                func.unaccent(func.lower(f"%{name_q}%"))
            )
        )

    if party_q:
        filters.append(
            Congresista.id.in_(
                select(Membership.person_id)
                .join(Organization, Organization.org_id == Membership.org_id)
                .where(
                    Membership.org_type == TypeOrganization.PARTY,
                    Organization.org_name == party_q,
                    Membership.leg_period == leg_period_q,
                )
            )
        )

    if region_q:
        filters.append(
            Congresista.id.in_(
                select(ChamberMembership.person_id)
                .where(ChamberMembership.dist_electoral == region_q)
                .distinct()
            )
        )

    if commission_q:
        filters.append(
            Congresista.id.in_(
                select(Membership.person_id)
                .join(Organization, Organization.org_id == Membership.org_id)
                .where(
                    Membership.org_type == TypeOrganization.COMMITTEE,
                    Organization.org_subtype.in_(
                        ordinary_committee_subtypes_for_period(leg_period_q)
                    ),
                    Organization.org_name == commission_q,
                    Membership.leg_period == leg_period_q,
                )
            )
        )

    if special_committee_q:
        filters.append(
            Congresista.id.in_(
                select(Membership.person_id)
                .join(Organization, Organization.org_id == Membership.org_id)
                .where(
                    Membership.org_type == TypeOrganization.COMMITTEE,
                    Organization.org_subtype == TypeCommittee.COM_ESP,
                    Organization.org_short_name == special_committee_q,
                )
            )
        )

    # Chamber + period as ONE combined subquery -- a person who held a
    # different chamber/period combination in another term must not match.
    # Always applied (not conditional on chamber_q): closes the previous
    # unbounded/unfiltered default listing.
    cm_filters = [ChamberMembership.leg_period == leg_period_q]
    if chamber_q:
        cm_filters.append(Organization.org_name == CHAMBER_UI_TO_ORG_NAME[chamber_q])
    filters.append(
        Congresista.id.in_(
            select(ChamberMembership.person_id)
            .join(Organization, Organization.org_id == ChamberMembership.org_id)
            .where(*cm_filters)
        )
    )

    with SessionProcessed() as db:
        party_options = create_party_option(db, leg_period_q)
        region_options = create_region_option(db)
        committee_options = create_committee_option(db, leg_period_q)
        special_committee_options = create_special_committee_option(db)

        count_stmt = select(func.count()).select_from(
            select(Congresista.id).where(*filters).subquery()
        )
        total_count = db.execute(count_stmt).scalar_one()
        total_pages = ceil(total_count / per_page) if total_count else 0
        if total_pages and page > total_pages:
            page = total_pages

        if total_pages:
            pagination_pages = [
                SimpleNamespace(
                    number=page_number,
                    current=page_number == page,
                    url=url_for("congress.index", page=page_number, **search_params),
                )
                for page_number in range(1, total_pages + 1)
            ]

        query = (
            select(Congresista)
            .where(*filters)
            .order_by(Congresista.full_name.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )

        rows = db.execute(query).scalars().all()
        if rows:
            results_start = (page - 1) * per_page + 1
            results_end = results_start + len(rows) - 1

        party_names, chamber_rows = _batch_congresista_extras(
            db, [row.id for row in rows], leg_period_q
        )
        congresistas = [
            _congresista_view_from_batch(
                row, party_names.get(row.id), chamber_rows.get(row.id)
            )
            for row in rows
        ]

    prev_page_url = None
    next_page_url = None
    if page > 1:
        prev_page_url = url_for("congress.index", page=page - 1, **search_params)
    if page < len(pagination_pages):
        next_page_url = url_for("congress.index", page=page + 1, **search_params)

    return render_template(
        "congress/search.html",
        name_q=name_q,
        party_q=party_q,
        region_q=region_q,
        commission_q=commission_q,
        special_committee_q=special_committee_q,
        chamber_q=chamber_q,
        chamber_display=chamber_display,
        leg_period_q=leg_period_q,
        leg_period_display=leg_period_display,
        leg_period_options=LEG_PERIOD_UI_OPTIONS,
        chamber_options=CHAMBER_UI_TO_ORG_NAME,
        congresistas=congresistas,
        party_options=party_options,
        region_options=region_options,
        committee_options=committee_options,
        special_committee_options=special_committee_options,
        page=page,
        per_page=per_page,
        total_count=total_count,
        results_start=results_start,
        results_end=results_end,
        pagination_pages=pagination_pages,
        prev_page_url=prev_page_url,
        next_page_url=next_page_url,
        search_params=search_params,
        period_tab_urls=period_tab_urls,
        chamber_tab_urls=chamber_tab_urls,
    )


@congress_bp.route("/congress/<int:congresista_id>/photo")
def congress_photo(congresista_id):
    with SessionProcessed() as db:
        congresista = db.get(Congresista, congresista_id)

        if not congresista:
            abort(404)

        if congresista.photo_bytes:
            return Response(
                congresista.photo_bytes,
                mimetype=_photo_mimetype(congresista.photo_bytes),
            )

        if congresista.photo_url:
            return redirect(
                congresista.photo_url.replace(
                    "https://www.congreso.gob.pe",
                    "https://www3.congreso.gob.pe",
                )
            )

    abort(404)


@congress_bp.route("/congress/<int:congresista_id>")
def congress_detail(congresista_id):
    with SessionProcessed() as db:
        congresista_row = db.get(Congresista, congresista_id)

        if not congresista_row:
            abort(404)

        period_data = _congresista_period_data(db, congresista_row.id)
        available_periods = [
            (value, label)
            for value, label, _enum in LEG_PERIOD_UI_OPTIONS
            if value in period_data
        ]
        requested_period = request.args.get("leg_period_q", "").strip()
        selected_period = (
            requested_period
            if requested_period in period_data
            else available_periods[0][0]
            if available_periods
            else None
        )

        if selected_period is None:
            # Defensive fallback: a congresista with zero ChamberMembership
            # rows at all (shouldn't happen in practice) keeps today's
            # "most recent ever, or blank" behavior.
            congresista = _congresista_view(db, congresista_row)
        else:
            period_info = period_data[selected_period]
            congresista = SimpleNamespace(
                id=congresista_row.id,
                full_name=congresista_row.full_name,
                first_name=congresista_row.first_name,
                last_name=congresista_row.last_name,
                photo_url=congresista_row.photo_url,
                website=congresista_row.website,
                party_name=period_info.party_name,
                dist_electoral=period_info.dist_electoral,
                condicion=period_info.condicion or _("No disponible"),
                votes_in_election=period_info.votes_in_election or 0,
                chamber_slug=period_info.chamber_slug,
            )

        # To avoid duplicated bills
        latest_bill_dates = (
            select(
                BillOrganization.bill_id,
                func.max(BillOrganization.presentation_date).label(
                    "latest_presentation_date"
                ),
            )
            .group_by(BillOrganization.bill_id)
            .subquery()
        )

        bill_in_selected_period = None
        if selected_period is not None:
            period_start, period_end = leg_period_date_range(selected_period)
            bill_in_selected_period = (
                select(BillOrganization.bill_id)
                .where(
                    BillOrganization.bill_id == Bill.id,
                    BillOrganization.presentation_date.between(
                        period_start, period_end
                    ),
                )
                .exists()
            )

        bill_filters = [Bill.author_id == congresista.id]
        if bill_in_selected_period is not None:
            bill_filters.append(bill_in_selected_period)

        bills_authored = [
            SimpleNamespace(
                id=bill.id,
                pley_id=bill.pley_id,
                title=bill.title,
                presentation_date=presentation_date,
            )
            for bill, presentation_date in db.execute(
                select(Bill, latest_bill_dates.c.latest_presentation_date)
                .join(latest_bill_dates, latest_bill_dates.c.bill_id == Bill.id)
                .where(*bill_filters)
                .order_by(latest_bill_dates.c.latest_presentation_date.desc())
                .limit(5)
            ).all()
        ]

        bills_authored_count = db.execute(
            select(func.count()).select_from(Bill).where(*bill_filters)
        ).scalar_one()

        successful_bills_count = db.execute(
            select(func.count())
            .select_from(Bill)
            .where(*bill_filters, Bill.bill_approved.is_(True))
        ).scalar_one()

        approval_rate_filters = [Bill.author_id.is_not(None)]
        if bill_in_selected_period is not None:
            approval_rate_filters.append(bill_in_selected_period)
        approval_rate_rows = db.execute(
            select(
                Bill.author_id,
                func.count(Bill.id).label("total_bills"),
                func.sum(case((Bill.bill_approved.is_(True), 1), else_=0)).label(
                    "approved_bills"
                ),
            )
            .where(*approval_rate_filters)
            .group_by(Bill.author_id)
        ).all()
        average_success_rate = (
            round(
                sum(
                    100 * (approved_bills / total_bills)
                    for _, total_bills, approved_bills in approval_rate_rows
                    if total_bills
                )
                / len(approval_rate_rows),
                1,
            )
            if approval_rate_rows
            else 0
        )

        membership_filters = [
            Membership.person_id == congresista.id,
            func.lower(Membership.role) != "accesitario",
            or_(
                Membership.org_type == TypeOrganization.COMMITTEE,
                Organization.org_type == TypeOrganization.COMMITTEE,
            ),
        ]
        if selected_period is not None:
            membership_filters.append(Membership.leg_period == selected_period)
        else:
            membership_filters.append(Membership.end_date >= date(2026, 7, 26))

        memberships = (
            db.execute(
                select(
                    Membership.role,
                    Membership.start_date,
                    Membership.end_date,
                    Organization.org_name,
                    Organization.org_type,
                    Organization.org_subtype,
                    Organization.org_short_name,
                )
                .join(Organization, Organization.org_id == Membership.org_id)
                .where(*membership_filters)
                .order_by(Membership.end_date.desc(), Membership.start_date.desc())
            )
            .mappings()
            .all()
        )

        profile_stats = {
            "assistance_rate": "45%",
            "bills_authored": bills_authored_count,
            "success_rate": f"{
                (
                    round(100 * (successful_bills_count / bills_authored_count), 1)
                    if bills_authored_count
                    else 0
                )
            } %",
            "average_success_rate": f"{average_success_rate} %",
            "successful_bills": successful_bills_count,
        }

        recent_votes = [
            {
                "position": _("A favor"),
                "bill": "Proyecto de ley N 32014",
                "description": _(
                    "Los datos de votación aún no están disponibles. Este es contenido temporal para la vista de detalle del congresista."
                ),
            },
            {
                "position": _("En contra"),
                "bill": "Proyecto de ley N 32074",
                "description": _(
                    "Los datos de votación aún no están disponibles. Este es contenido temporal para la vista de detalle del congresista."
                ),
            },
        ]

        selected_period_label = next(
            (label for value, label in available_periods if value == selected_period),
            None,
        )

        return render_template(
            "congress/congress_detail.html",
            congresista=congresista,
            memberships=memberships,
            bills_authored=bills_authored,
            profile_stats=profile_stats,
            recent_votes=recent_votes,
            available_periods=available_periods,
            selected_period=selected_period,
            selected_period_label=selected_period_label,
        )
