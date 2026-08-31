from math import ceil

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.core.enums import TypeBillStep, TypeOrganization, TypeRoleBill
from backend.database.models import (
    Bill,
    BillCongresistas,
    BillOrganization,
    BillStep,
    Congresista,
    Ley,
    Membership,
    Organization,
)


TOPIC_MAPPING = {
    "InclusiÃ³n Social y Personas con Discapacidad": [
        "InclusiÃ³n Social",
        "Discapacidad",
    ],
    "Defensa del Consumidor y Organismos Reguladores de los Servicios PÃºblicos": [
        "Defensa del Consumidor",
        "RegulaciÃ³n y Competencia",
    ],
    "Relaciones Exteriores": ["Relaciones Exteriores"],
    "Defensa Nacional, Orden interno, Desarrollo alternativo y Lucha contra las Drogas": [
        "Defensa Nacional",
        "Orden Interno",
        "Desarrollo alternativo y Lucha contra las Drogas",
    ],
    "Presupuesto y Cuenta General de la RepÃºblica": ["Presupuesto"],
    "Pueblos Andinos, AmazÃ³nicos y Afroperuanos, Ambiente y EcologÃ­a": [
        "Pueblos Andinos, AmazÃ³nicos y Afroperuanos",
        "Ambiente y EcologÃ­a",
    ],
    "Mujer y Familia": ["Mujer y Familia"],
    "Transportes y Comunicaciones": ["Transportes y Comunicaciones"],
    "EnergÃ­a y Minas": ["EnergÃ­a y Minas"],
    "EducaciÃ³n, Juventud y Deporte": ["EducaciÃ³n, Juventud y Deporte"],
    "DescentralizaciÃ³n, RegionalizaciÃ³n, Gobiernos Locales y ModernizaciÃ³n de la GestiÃ³n del Estado": [
        "DescentralizaciÃ³n",
        "ModernizaciÃ³n del Estado",
    ],
    "FiscalizaciÃ³n y ContralorÃ­a": ["FiscalizaciÃ³n y ContralorÃ­a"],
    "ConstituciÃ³n y Reglamento": ["ConstituciÃ³n y Reglamento"],
    "Justicia y Derechos Humanos": ["Justicia y Derechos Humanos"],
    "Ciencia, InnovaciÃ³n y TecnologÃ­a": ["Ciencia, InnovaciÃ³n y TecnologÃ­a"],
    "Trabajo y Seguridad Social": ["Trabajo y Seguridad Social"],
    "Salud y PoblaciÃ³n": ["Salud y PoblaciÃ³n"],
    "Cultura y Patrimonio Cultural": ["Cultura y Patrimonio Cultural"],
    "Vivienda y ConstrucciÃ³n": ["Vivienda y ConstrucciÃ³n"],
    "Agraria": ["Agraria"],
    "ProducciÃ³n, Micro y PequeÃ±a Empresa y Cooperativas": [
        "ProducciÃ³n, Micro y PequeÃ±a Empresa y Cooperativas"
    ],
    "Inteligencia": ["Inteligencia"],
    "Comercio Exterior y Turismo": ["Comercio Exterior y Turismo"],
    "EconomÃ­a, Banca, Finanzas e Inteligencia Financiera": [
        "EconomÃ­a",
        "Banca y Finanzas",
        "Inteligencia Financiera",
    ],
}


def _enum_value(value):
    return getattr(value, "value", value)


def _bill_step_to_dict(step: BillStep | None) -> dict | None:
    if step is None:
        return None

    return {
        "step_id": step.step_id,
        "step_type": _enum_value(step.step_type),
        "vote_step": step.vote_step,
        "step_date": step.step_date,
        "step_detail": step.step_detail,
    }


def search_bills(db: Session, args: dict) -> dict:
    """Search bills for the public API list endpoint."""
    page = args["page"]
    per_page = args["per_page"]

    latest_bill_dates = (
        select(
            BillOrganization.bill_id,
            func.max(BillOrganization.presentation_date).label("presentation_date"),
        )
        .group_by(BillOrganization.bill_id)
        .subquery()
    )

    stmt = (
        select(
            Bill.id.label("id"),
            Bill.pley_id.label("pley_id"),
            Bill.title.label("title"),
            Bill.status.label("status"),
            Bill.proponent.label("proponent"),
            Bill.author_id.label("author_id"),
            Congresista.full_name.label("author_name"),
            latest_bill_dates.c.presentation_date.label("presentation_date"),
            Bill.bill_approved.label("approved"),
        )
        .join(Congresista, Bill.author_id == Congresista.id, isouter=True)
        .join(latest_bill_dates, latest_bill_dates.c.bill_id == Bill.id)
    )

    filters = []

    if args.get("title"):
        filters.append(
            func.unaccent(func.lower(Bill.title)).like(
                func.unaccent(func.lower(f"%{args['title']}%"))
            )
        )

    if args.get("author"):
        filters.append(
            func.unaccent(func.lower(Congresista.full_name)).like(
                func.unaccent(func.lower(f"%{args['author']}%"))
            )
        )

    if args.get("author_id") is not None:
        filters.append(Bill.author_id == args["author_id"])

    if args.get("status"):
        filters.append(Bill.status == args["status"])

    if args.get("pley_id"):
        filters.append(Bill.pley_id.ilike(f"%{args['pley_id']}%"))

    if args.get("law_id"):
        filters.append(
            select(Ley.id)
            .where(Ley.bill_id == Bill.id, Ley.id.ilike(f"%{args['law_id']}%"))
            .exists()
        )

    if args.get("presentation_date_from"):
        filters.append(
            latest_bill_dates.c.presentation_date >= args["presentation_date_from"]
        )

    if args.get("presentation_date_to"):
        filters.append(
            latest_bill_dates.c.presentation_date <= args["presentation_date_to"]
        )

    if filters:
        stmt = stmt.where(*filters)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    rows = (
        db.execute(
            stmt.order_by(
                latest_bill_dates.c.presentation_date.desc(),
                Bill.title.asc(),
                Bill.id.asc(),
            )
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        .mappings()
        .all()
    )

    items = []
    for row in rows:
        item = dict(row)
        item["proponent"] = _enum_value(item.get("proponent"))
        items.append(item)

    return {
        "items": items,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": ceil(total / per_page) if total else 0,
        },
    }


def get_bill_author_id(db: Session, bill: Bill) -> int | None:
    """Return the primary author id, falling back to BillCongresistas."""
    if bill.author_id:
        return bill.author_id

    return db.scalar(
        select(BillCongresistas.person_id)
        .where(
            BillCongresistas.bill_id == bill.id,
            BillCongresistas.role_type == TypeRoleBill.AUTHOR,
        )
        .limit(1)
    )


def get_author_with_party(
    db: Session, author_id: int | None
) -> tuple[dict | None, str | None]:
    """Return author API data and latest known party name."""
    if not author_id:
        return None, None

    author = db.get(Congresista, author_id)
    if author is None:
        return None, None

    party_name = db.scalar(
        select(Organization.org_name)
        .join(Membership, Membership.org_id == Organization.org_id)
        .where(
            Membership.person_id == author_id,
            Membership.org_type == TypeOrganization.PARTY,
        )
        .order_by(desc(Membership.end_date), desc(Membership.start_date))
        .limit(1)
    )

    return (
        {
            "full_name": author.full_name,
            "id": author.id,
            "last_name": author.last_name,
            "first_name": author.first_name,
        },
        party_name,
    )


def get_bill_topics(db: Session, bill_id: str) -> list[str]:
    """Infer bill topics from ordinary committee assignments."""
    committees = db.scalars(
        select(Organization.org_name)
        .join(BillOrganization, BillOrganization.org_id == Organization.org_id)
        .where(
            Organization.org_type == TypeOrganization.COMMITTEE,
            Organization.org_subtype == "ComisiÃ³n Ordinaria",
            BillOrganization.bill_id == bill_id,
        )
        .distinct()
        .order_by(Organization.org_name)
    ).all()

    topics = []
    for committee in committees:
        topics.extend(TOPIC_MAPPING.get(committee, []))

    return topics


def get_bill_steps(db: Session, bill_id: str) -> tuple[list[dict], dict | None]:
    """Return bill steps ordered latest-first, plus the latest step."""
    steps = (
        db.execute(
            select(BillStep)
            .where(BillStep.bill_id == bill_id)
            .order_by(desc(BillStep.step_date), desc(BillStep.step_id))
        )
        .scalars()
        .all()
    )
    step_items = [_bill_step_to_dict(step) for step in steps]
    latest_step = step_items[0] if step_items else None
    return step_items, latest_step


def get_presentation_date(db: Session, bill_id: str):
    """Return the bill presentation date used by the detail view."""
    return db.scalar(
        select(BillStep.step_date)
        .where(
            BillStep.bill_id == bill_id,
            BillStep.step_type == TypeBillStep.PRESENTADO,
        )
        .order_by(BillStep.step_date.asc(), BillStep.step_id.asc())
        .limit(1)
    )


def get_ley_id(db: Session, bill_id: str) -> str | None:
    """Return the law number associated with a bill, if any."""
    return db.scalar(select(Ley.id).where(Ley.bill_id == bill_id).limit(1))


def get_approval_date(db: Session, bill_id: str):
    """Return the latest voting date used as the bill approval date."""
    return db.scalar(
        select(BillStep.step_date)
        .where(
            BillStep.bill_id == bill_id,
            BillStep.step_type == TypeBillStep.VOTACION,
        )
        .order_by(desc(BillStep.step_date))
        .limit(1)
    )


def get_days_since_presentation(db: Session, bill: Bill, presentation_date):
    """Return days until approval, or days since presentation if not approved."""
    if presentation_date is None:
        return None

    if bill.bill_approved:
        approval_date = get_approval_date(db, bill.id)
        if approval_date is None:
            return None
        return (approval_date - presentation_date).days

    from datetime import datetime

    return (datetime.now().date() - presentation_date).days


def get_bill_detail(db: Session, bill_id: str) -> dict | None:
    """Return API-ready bill detail data with nested bill steps."""
    bill = db.get(Bill, bill_id)
    if bill is None:
        return None

    author_id = get_bill_author_id(db, bill)
    author, party_name = get_author_with_party(db, author_id)
    bill_steps, latest_step = get_bill_steps(db, bill_id)
    presentation_date = get_presentation_date(db, bill_id)

    return {
        "id": bill.id,
        "pley_id": bill.pley_id,
        "ley_id": get_ley_id(db, bill_id),
        "title": bill.title,
        "summary_congreso": bill.summary_congreso,
        "proponent": _enum_value(bill.proponent),
        "status": bill.status,
        "approval_status": "Aprobado" if bill.bill_approved else "No aprobado",
        "approved": bill.bill_approved,
        "days_since_presentation": get_days_since_presentation(
            db,
            bill,
            presentation_date,
        ),
        "observations": bill.observations,
        "author": author,
        "party": party_name,
        "presentation_date": presentation_date,
        "latest_step": latest_step,
        "topics": get_bill_topics(db, bill_id),
        "bill_steps": bill_steps,
    }


def get_bill_detail_by_period_and_pl(
    db: Session,
    period: int,
    pl_number: int,
) -> dict | None:
    """Return bill detail using the public PL number plus legislative period."""
    bill_id = f"{period}_{pl_number}"
    return get_bill_detail(db, bill_id)
