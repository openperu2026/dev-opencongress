"""Tests for the bill detail page's per-step ``View changes`` link.

The link should only appear for steps whose ``BillDifference`` row carries
content the user can actually see (``modified`` or ``incomparable``).
Steps with no diff row, ``no_change``, ``unavailable``, or ``first_version``
must not surface the link.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.enums import Proponents, TypeBillStep
from backend.database.models import (
    Base,
    Bill,
    BillDifference,
    BillStep,
)


@pytest.fixture()
def session_factory(tmp_path):
    db_path = tmp_path / "processed_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


@pytest.fixture()
def client(monkeypatch, session_factory):
    import app.routes.bills as bills_module
    from app.app import create_app

    monkeypatch.setattr(bills_module, "SessionProcessed", session_factory)
    flask_app = create_app()
    flask_app.testing = True
    return flask_app.test_client()


def _seed(session_factory, *, steps_with_diff_types):
    """Seed a bill with one step per entry; each entry is (step_id, diff_type | None)."""
    bill_id = "2021_1234"
    with session_factory() as db:
        db.add(
            Bill(
                id=bill_id,
                title="Test bill",
                summary_congreso="",
                observations="",
                status="presentado",
                proponent=Proponents.CONGRESO,
                bill_approved=False,
                summary_oc="",
            )
        )
        for step_id, diff_type in steps_with_diff_types:
            db.add(
                BillStep(
                    bill_id=bill_id,
                    step_id=step_id,
                    vote_step=False,
                    step_date=date(2022, 2, step_id),
                    step_type=TypeBillStep.DICTAMEN_O_ACUERDO_DE_COMISION,
                    step_detail="",
                )
            )
            if diff_type is not None:
                db.add(
                    BillDifference(
                        bill_id=bill_id,
                        step_id=step_id,
                        prev_step_id=None,
                        difference_type=diff_type,
                        difference_content=None,
                    )
                )
        db.commit()


def test_view_changes_link_only_for_modified_and_incomparable(client, session_factory):
    _seed(
        session_factory,
        steps_with_diff_types=[
            (1, "modified"),
            (2, "no_change"),
            (3, "unavailable"),
            (4, "first_version"),
            (5, "incomparable"),
            (6, None),  # no BillDifference row
        ],
    )

    body = client.get("/bills/2021_1234").get_data(as_text=True)

    assert "/bills/2021_1234/difference/1" in body  # modified → linked
    assert "/bills/2021_1234/difference/5" in body  # incomparable → linked
    assert "/bills/2021_1234/difference/2" not in body  # no_change → hidden
    assert "/bills/2021_1234/difference/3" not in body  # unavailable → hidden
    assert "/bills/2021_1234/difference/4" not in body  # first_version → hidden
    assert "/bills/2021_1234/difference/6" not in body  # missing row → hidden
