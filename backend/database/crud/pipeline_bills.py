from __future__ import annotations

from enum import Enum
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import OcrModel
from backend.database import models as db_models
from backend.process import schema
from backend.database.crud.pipeline_core import (
    find_congresista,
    _enum_value,
)
from backend.database.raw_models import RawBillDocument, RawBillPage


def upsert_bill(db: Session, schema: schema.Bill) -> db_models.Bill:
    author = None
    if schema.author_name:
        author = find_congresista(
            db,
            name=schema.author_name,
            website=schema.author_web,
        )

    payload = {
        "id": schema.id,
        "title": schema.title,
        "summary_congreso": schema.summary_congreso,
        "observations": schema.observations or "",
        "status": schema.status,
        "proponent": schema.proponent.value
        if hasattr(schema.proponent, "value")
        else schema.proponent,
        "author_id": author.id if author else None,
        "bill_approved": schema.bill_approved,
        "summary_oc": schema.summary_oc,
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
    db: Session,
    bill_id: str,
    person_id: int,
    role_type: Enum | str,
) -> db_models.BillCongresistas:
    existing = db.get(db_models.BillCongresistas, (bill_id, person_id))
    role_type = _enum_value(role_type)

    if existing is None:
        obj = db_models.BillCongresistas(
            bill_id=bill_id,
            person_id=person_id,
            role_type=role_type,
        )
        db.add(obj)
        db.flush()
        return obj

    existing.role_type = role_type
    db.flush()
    return existing


def upsert_bill_organization(
    db: Session, bill_id: str, org_id: int, schema: schema.BillOrganization
) -> db_models.BillOrganization:
    existing = (
        db.query(db_models.BillOrganization)
        .filter(
            db_models.BillOrganization.bill_id == bill_id,
            db_models.BillOrganization.org_id == org_id,
        )
        .first()
    )
    payload = {
        "bill_id": bill_id,
        "org_id": org_id,
        "org_type": schema.org_type.value
        if hasattr(schema.org_type, "value")
        else schema.org_type,
        "presentation_date": schema.presentation_date,
        "decision_date": schema.decision_date,
    }

    if existing is not None:
        for key, value in payload.items():
            setattr(existing, key, value)
        db.flush()
        return existing

    obj = db_models.BillOrganization(**payload)
    db.add(obj)
    db.flush()
    return obj


def upsert_bill_step(
    db: Session,
    schema: schema.BillStep,
) -> db_models.BillStep:
    existing = db.get(db_models.BillStep, (schema.bill_id, schema.step_id))
    step_type = (
        schema.step_type.value
        if hasattr(schema.step_type, "value")
        else schema.step_type
    )
    payload = {
        "bill_id": schema.bill_id,
        "step_id": schema.step_id,
        "vote_step": schema.vote_step,
        "vote_event_id": schema.vote_event_id,
        "step_type": step_type,
        "step_date": schema.step_date,
        "step_detail": schema.step_detail,
    }
    if existing is None:
        obj = db_models.BillStep(**payload)
        db.add(obj)
        db.flush()
        return obj

    for key, value in payload.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def find_raw_bill_documents(raw_db: Session, bill_id: str) -> list[RawBillDocument]:
    return (
        raw_db.query(RawBillDocument)
        .filter(
            RawBillDocument.bill_id == bill_id,
            RawBillDocument.last_update.is_(True),
            RawBillDocument.processed.is_(False),
        )
        .all()
    )


def find_raw_bill_pages(
    raw_db: Session,
    bill_id: str,
    step_id: str | int,
    file_id: str | int,
    ocr_model: str = OcrModel.CHANDRA.value,
) -> list[RawBillPage]:
    """Return the latest pages of a bill document for a single OCR model.

    Since the ``feature/data_migration`` migration, ``raw_bill_pages`` is keyed
    by ``ocr_model`` as well, so a document can hold one page row per model.
    Filtering by ``ocr_model`` keeps the page sequence unambiguous; bills are
    OCR'd with chandra2, hence the default.
    """
    return (
        raw_db.query(RawBillPage)
        .filter(
            RawBillPage.bill_id == bill_id,
            RawBillPage.step_id == str(step_id),
            RawBillPage.file_id == str(file_id),
            RawBillPage.ocr_model == ocr_model,
            RawBillPage.last_update.is_(True),
        )
        .order_by(RawBillPage.page_num)
        .all()
    )


def upsert_bill_text(
    db: Session,
    *,
    bill_id: str,
    step_id: int,
    file_id: int,
    version_id: int,
    text: str,
) -> db_models.BillText:
    existing = db.get(db_models.BillText, (bill_id, step_id, file_id, version_id))
    payload = {
        "bill_id": bill_id,
        "step_id": step_id,
        "file_id": file_id,
        "version_id": version_id,
        "text": text,
    }
    if existing is None:
        row = db_models.BillText(**payload)
        db.add(row)
        db.flush()
        return row
    for key, value in payload.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def get_billtext_for_step(
    db: Session, bill_id: str, step_id: int
) -> db_models.BillText | None:
    """
    Return the canonical BillText for a step.

    A step may have multiple rows in ``bill_texts`` (different file_id /
    version_id). The diff feature treats one step as one logical text;
    pick the highest ``version_id`` for the lowest ``file_id`` so the
    selection is stable across pipeline runs.
    """
    stmt = (
        select(db_models.BillText)
        .where(
            db_models.BillText.bill_id == bill_id,
            db_models.BillText.step_id == step_id,
        )
        .order_by(
            db_models.BillText.file_id.asc(),
            db_models.BillText.version_id.desc(),
        )
    )
    return db.execute(stmt).scalars().first()


def upsert_bill_difference(
    db: Session,
    *,
    bill_id: str,
    step_id: int,
    prev_step_id: int | None,
    difference_type: str,
    difference_content: str | None,
) -> db_models.BillDifference:
    existing = db.get(db_models.BillDifference, (bill_id, step_id))
    if existing is None:
        row = db_models.BillDifference(
            bill_id=bill_id,
            step_id=step_id,
            prev_step_id=prev_step_id,
            difference_type=difference_type,
            difference_content=difference_content,
        )
        db.add(row)
        db.flush()
        return row
    existing.prev_step_id = prev_step_id
    existing.difference_type = difference_type
    existing.difference_content = difference_content
    db.flush()
    return existing
