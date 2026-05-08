from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import models as db_models
from backend.database.crud.pipeline_core import find_congresista
from backend.database.raw_models import RawBillDocument


def upsert_bill(db: Session, schema) -> db_models.Bill:
    author = None
    if schema.author_name:
        author = find_congresista(
            db,
            name=schema.author_name,
            leg_period=schema.leg_period,
            website=schema.author_web,
        )

    payload = {
        "id": schema.id,
        "leg_period": schema.leg_period,
        "legislature": schema.legislature,
        "presentation_date": schema.presentation_date,
        "title": schema.title,
        "summary": schema.summary,
        "observations": schema.observations or "",
        "complete_text": schema.complete_text or "",
        "status": schema.status,
        "proponent": schema.proponent,
        "author_id": author.id if author else None,
        "bancada_id": None,
        "bill_approved": schema.bill_approved,
    }

    existing = db.get(db_models.Bill, schema.id)
    if existing is None:
        obj = db_models.Bill(**payload)
        db.add(obj)
        db.flush()
        return obj

    for key, value in payload.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def upsert_bill_congresista(
    db: Session, bill_id: str, person_id: int, role_type
) -> db_models.BillCongresistas:
    existing = db.get(db_models.BillCongresistas, (bill_id, person_id))
    if existing is None:
        obj = db_models.BillCongresistas(
            bill_id=bill_id, person_id=person_id, role_type=role_type
        )
        db.add(obj)
        db.flush()
        return obj

    existing.role_type = role_type
    db.flush()
    return existing


def upsert_bill_committee(
    db: Session, bill_id: str, committee_id: int
) -> db_models.BillCommittees:
    existing = (
        db.query(db_models.BillCommittees)
        .filter(
            db_models.BillCommittees.bill_id == bill_id,
            db_models.BillCommittees.committee_id == committee_id,
        )
        .first()
    )
    if existing is not None:
        return existing

    obj = db_models.BillCommittees(bill_id=bill_id, committee_id=committee_id)
    db.add(obj)
    db.flush()
    return obj


def upsert_bill_step(
    db: Session,
    step_id: int,
    bill_id: str,
    step_date,
    step_detail: str,
    step_status: str | None = None,
    vote_step: bool = False,
    vote_id: str | None = None,
) -> db_models.BillStep:
    existing = db.get(db_models.BillStep, step_id)
    if existing is None:
        obj = db_models.BillStep(
            id=step_id,
            bill_id=bill_id,
            vote_step=vote_step,
            vote_event_id=vote_id,
            step_type=step_status,
            step_date=step_date,
            step_detail=step_detail,
        )
        db.add(obj)
        db.flush()
        return obj

    existing.bill_id = bill_id
    existing.vote_step = vote_step
    existing.vote_event_id = vote_id
    existing.step_type = step_status
    existing.step_date = step_date
    existing.step_detail = step_detail
    db.flush()
    return existing


def find_raw_bill_documents(raw_db: Session, bill_id: str) -> Iterable[RawBillDocument]:
    return (
        raw_db.query(RawBillDocument)
        .filter(
            RawBillDocument.bill_id == bill_id,
            RawBillDocument.last_update.is_(True),
            RawBillDocument.processed.is_(False),
        )
        .all()
    )


def upsert_bill_document(
    db: Session,
    bill_id: str,
    step_id: int,
    archivo_id: int,
    url: str,
    text: str,
    vote_doc: bool,
) -> db_models.BillDocument:
    existing = db.get(db_models.BillDocument, archivo_id)
    if existing is None:
        obj = db_models.BillDocument(
            bill_id=bill_id,
            step_id=step_id,
            archivo_id=archivo_id,
            url=url,
            text=text,
            vote_doc=vote_doc,
        )
        db.add(obj)
        db.flush()
        return obj

    existing.bill_id = bill_id
    existing.step_id = step_id
    existing.url = url
    existing.text = text
    existing.vote_doc = vote_doc
    db.flush()
    return existing


def upsert_bill_text(
    db: Session,
    *,
    archivo_id: int,
    bill_id: str,
    step_date,
    seguimiento_id: str,
    text: str | None,
) -> db_models.BillText:
    existing = db.get(db_models.BillText, archivo_id)
    if existing is None:
        row = db_models.BillText(
            archivo_id=archivo_id,
            bill_id=bill_id,
            step_date=step_date,
            seguimiento_id=seguimiento_id,
            text=text,
        )
        db.add(row)
        db.flush()
        return row
    existing.bill_id = bill_id
    existing.step_date = step_date
    existing.seguimiento_id = seguimiento_id
    existing.text = text
    db.flush()
    return existing


def get_billtext_for_step(db: Session, step_id: int) -> db_models.BillText | None:
    """
    Return the BillText for a given step_id, preferring a non-vote document.
    Falls back to any document if all are vote docs.
    """
    stmt = (
        select(db_models.BillText)
        .join(
            db_models.BillDocument,
            db_models.BillText.archivo_id == db_models.BillDocument.archivo_id,
        )
        .where(db_models.BillDocument.step_id == step_id)
        .order_by(
            db_models.BillDocument.vote_doc.asc(),
            db_models.BillDocument.archivo_id.asc(),
        )
    )
    return db.execute(stmt).scalars().first()


def upsert_bill_difference(
    db: Session,
    *,
    step_id: int,
    bill_id: str,
    prev_step_id: int | None,
    new_archivo_id: int | None,
    old_archivo_id: int | None,
    difference_type: str,
    difference_content: str | None,
) -> db_models.BillDifference:
    existing = db.get(db_models.BillDifference, step_id)
    if existing is None:
        row = db_models.BillDifference(
            step_id=step_id,
            bill_id=bill_id,
            prev_step_id=prev_step_id,
            new_archivo_id=new_archivo_id,
            old_archivo_id=old_archivo_id,
            difference_type=difference_type,
            difference_content=difference_content,
        )
        db.add(row)
        db.flush()
        return row
    existing.bill_id = bill_id
    existing.prev_step_id = prev_step_id
    existing.new_archivo_id = new_archivo_id
    existing.old_archivo_id = old_archivo_id
    existing.difference_type = difference_type
    existing.difference_content = difference_content
    db.flush()
    return existing
