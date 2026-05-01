from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.crud.pipeline_bills import upsert_bill_text
from backend.database.models import (
    Base,
    Bill,
    BillDocument,
    BillStep,
    BillText,
    LegPeriod,
    Legislature,
    Proponents,
)
from backend import BillStepType


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def _minimal_bill_and_document(db, bill_id: str, step_id: int, archivo_id: int):
    db.add(
        Bill(
            id=bill_id,
            leg_period=LegPeriod.PERIODO_2021_2026,
            legislature=Legislature.LEGISLATURA_2021_1,
            presentation_date=datetime(2024, 1, 1),
            title="t",
            summary="s",
            observations="o",
            complete_text="",
            status="st",
            proponent=Proponents.CONGRESO,
            author_id=None,
            bancada_id=None,
            approved=False,
        )
    )
    db.add(
        BillStep(
            id=step_id,
            bill_id=bill_id,
            vote_step=False,
            vote_event_id=None,
            step_type=BillStepType.VOTACION,
            step_date=datetime(2024, 1, 2),
            step_detail="d",
        )
    )
    db.add(
        BillDocument(
            bill_id=bill_id,
            step_id=step_id,
            archivo_id=archivo_id,
            url="http://example.com/x",
            text="raw doc",
            vote_doc=False,
        )
    )
    db.commit()


def test_upsert_bill_text_insert(session):
    _minimal_bill_and_document(session, "BILL_BT", 5001, 9001)
    step_date = datetime(2024, 3, 1)
    row = upsert_bill_text(
        session,
        archivo_id=9001,
        bill_id="BILL_BT",
        step_date=step_date,
        seguimiento_id="5001",
        text="PROYECTO DE LEY …",
    )
    session.commit()
    assert row.archivo_id == 9001
    assert row.text == "PROYECTO DE LEY …"

    loaded = session.get(BillText, 9001)
    assert loaded is not None
    assert loaded.bill_id == "BILL_BT"
    assert loaded.step_date == step_date
    assert loaded.seguimiento_id == "5001"


def test_upsert_bill_text_update_same_archivo(session):
    _minimal_bill_and_document(session, "BILL_BT2", 5002, 9002)
    d1 = datetime(2024, 4, 1)
    d2 = datetime(2024, 5, 1)
    upsert_bill_text(
        session,
        archivo_id=9002,
        bill_id="BILL_BT2",
        step_date=d1,
        seguimiento_id="a",
        text="first",
    )
    session.commit()
    upsert_bill_text(
        session,
        archivo_id=9002,
        bill_id="BILL_BT2",
        step_date=d2,
        seguimiento_id="b",
        text="second",
    )
    session.commit()

    rows = session.query(BillText).filter_by(archivo_id=9002).all()
    assert len(rows) == 1
    assert rows[0].text == "second"
    assert rows[0].step_date == d2
    assert rows[0].seguimiento_id == "b"


def test_upsert_bill_text_null_text(session):
    _minimal_bill_and_document(session, "BILL_BT3", 5003, 9003)
    upsert_bill_text(
        session,
        archivo_id=9003,
        bill_id="BILL_BT3",
        step_date=datetime(2024, 6, 1),
        seguimiento_id="x",
        text=None,
    )
    session.commit()
    loaded = session.get(BillText, 9003)
    assert loaded is not None
    assert loaded.text is None
