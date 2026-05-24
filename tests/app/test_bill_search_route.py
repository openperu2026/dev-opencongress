from __future__ import annotations

from backend.core.enums import Proponents
from backend.database.models import Base, Bill

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


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


def _seed_bills(session_factory, count: int) -> None:
    with session_factory() as db:
        for index in range(1, count + 1):
            db.add(
                Bill(
                    id=f"2021_{index:04d}",
                    title=f"Bill {index:04d}",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    bill_approved=False,
                    summary_oc="",
                )
            )
        db.commit()


def test_search_results_are_paginated_by_50(client, session_factory):
    _seed_bills(session_factory, 55)

    first_page = client.get("/bills?title_q=Bill")
    first_body = first_page.get_data(as_text=True)
    assert first_page.status_code == 200
    assert "Showing 1-50 of 55 bills" in first_body
    assert "Bill 0001" in first_body
    assert "Bill 0050" in first_body
    assert "Bill 0051" not in first_body
    assert "page=2" in first_body

    second_page = client.get("/bills?title_q=Bill&page=2")
    second_body = second_page.get_data(as_text=True)
    assert second_page.status_code == 200
    assert "Showing 51-55 of 55 bills" in second_body
    assert "Bill 0051" in second_body
    assert "Bill 0055" in second_body
    assert "Bill 0001" not in second_body
    assert "page=1" in second_body


def test_search_results_cap_at_500_plus(client, session_factory):
    _seed_bills(session_factory, 501)

    first_page = client.get("/bills?title_q=Bill")
    body = first_page.get_data(as_text=True)

    assert first_page.status_code == 200
    assert "Showing 1-50 of 500+ bills" in body
    assert "page=10" in body
    assert "page=11" not in body
