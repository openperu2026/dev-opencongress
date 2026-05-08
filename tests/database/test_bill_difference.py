from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.crud.pipeline_bills import (
    upsert_bill_difference,
    get_billtext_for_step,
)
from backend.database.models import (
    Base,
    Bill,
    BillDocument,
    BillDifference,
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


def _setup(
    db, bill_id="BILL_1", step_id=1, archivo_id=100, vote_doc=False, text="body"
):
    db.add(
        Bill(
            id=bill_id,
            leg_period=LegPeriod.PERIODO_2021_2026,
            legislature=Legislature.LEGISLATURA_2021_1,
            presentation_date=datetime(2024, 1, 1),
            title="t",
            summary="s",
            observations="",
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
            url="http://x.com",
            text="raw",
            vote_doc=vote_doc,
        )
    )
    db.add(
        BillText(
            archivo_id=archivo_id,
            bill_id=bill_id,
            step_date=datetime(2024, 1, 2),
            seguimiento_id=str(step_id),
            text=text,
        )
    )
    db.commit()


def test_upsert_bill_difference_insert(session):
    _setup(session)
    row = upsert_bill_difference(
        session,
        step_id=1,
        bill_id="BILL_1",
        prev_step_id=None,
        new_archivo_id=100,
        old_archivo_id=None,
        difference_type="first_version",
        difference_content=None,
    )
    session.commit()
    assert row.step_id == 1
    assert row.difference_type == "first_version"
    loaded = session.get(BillDifference, 1)
    assert loaded is not None
    assert loaded.bill_id == "BILL_1"
    assert loaded.prev_step_id is None


def test_upsert_bill_difference_update(session):
    _setup(session)
    upsert_bill_difference(
        session,
        step_id=1,
        bill_id="BILL_1",
        prev_step_id=None,
        new_archivo_id=100,
        old_archivo_id=None,
        difference_type="first_version",
        difference_content=None,
    )
    session.commit()
    upsert_bill_difference(
        session,
        step_id=1,
        bill_id="BILL_1",
        prev_step_id=None,
        new_archivo_id=100,
        old_archivo_id=None,
        difference_type="modified",
        difference_content='["+ line"]',
    )
    session.commit()
    rows = session.query(BillDifference).filter_by(step_id=1).all()
    assert len(rows) == 1
    assert rows[0].difference_type == "modified"
    assert rows[0].difference_content == '["+ line"]'


def test_get_billtext_for_step_prefers_non_vote(session):
    _setup(session, step_id=10, archivo_id=200, vote_doc=False, text="main body")
    # add a vote doc for the same step
    session.add(
        BillDocument(
            bill_id="BILL_1",
            step_id=10,
            archivo_id=201,
            url="http://x.com/vote",
            text="vote raw",
            vote_doc=True,
        )
    )
    session.add(
        BillText(
            archivo_id=201,
            bill_id="BILL_1",
            step_date=datetime(2024, 1, 2),
            seguimiento_id="10",
            text="vote body",
        )
    )
    session.commit()

    bt = get_billtext_for_step(session, 10)
    assert bt is not None
    assert bt.archivo_id == 200  # non-vote preferred


def test_get_billtext_for_step_missing_returns_none(session):
    assert get_billtext_for_step(session, 9999) is None
