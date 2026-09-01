from __future__ import annotations

from datetime import date
from pathlib import Path
import unicodedata
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.core.enums import (
    Proponents,
    TypeBillStep,
    TypeCommittee,
    TypeOrganization,
)
from backend.database.models import (
    Base,
    Bill,
    BillOrganization,
    BillStep,
    ChamberMembership,
    Congresista,
    Ley,
    Organization,
    PartyMembership,
)


def _register_sqlite_functions(engine):
    @event.listens_for(engine, "connect")
    def _sqlite_functions_on_connect(dbapi_connection, connection_record):
        if dbapi_connection.__class__.__module__.startswith("sqlite3"):
            dbapi_connection.create_function(
                "unaccent",
                1,
                lambda value: (
                    None
                    if value is None
                    else "".join(
                        character
                        for character in unicodedata.normalize("NFKD", str(value))
                        if not unicodedata.combining(character)
                    )
                ),
            )


@pytest.fixture()
def session_factory():
    temp_dir = Path.cwd() / ".pytest_api_tmp"
    temp_dir.mkdir(exist_ok=True)
    db_path = temp_dir / f"api_test_{uuid4().hex}.db"
    engine = create_engine(f"sqlite:///{db_path}")
    _register_sqlite_functions(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()
    db_path.unlink(missing_ok=True)


@pytest.fixture()
def client(monkeypatch, session_factory):
    import app.routes.api.bills as api_bills_module
    import app.routes.api.congress as api_congress_module
    from app.app import create_app

    monkeypatch.setattr(api_bills_module, "SessionProcessed", session_factory)
    monkeypatch.setattr(api_congress_module, "SessionProcessed", session_factory)

    flask_app = create_app()
    flask_app.testing = True
    return flask_app.test_client()


@pytest.fixture()
def seeded_api_data(session_factory):
    with session_factory() as db:
        db.add_all(
            [
                Organization(
                    org_id=1,
                    org_name="Congreso",
                    org_type=TypeOrganization.CHAMBER,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=2,
                    org_name="Fuerza Popular",
                    org_type=TypeOrganization.PARTY,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=3,
                    org_name="ComisiÃ³n Test",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Congresista(
                    id=10,
                    full_name="Diana Carolina Gonzales Delgado",
                    first_name="Diana Carolina",
                    last_name="Gonzales Delgado",
                    dni="00000010",
                    gender="F",
                    photo_url="https://example.com/photo.jpg",
                    website="https://example.com",
                ),
                Congresista(
                    id=11,
                    full_name="Juan Perez",
                    first_name="Juan",
                    last_name="Perez",
                    dni="00000011",
                    gender="M",
                    photo_url="",
                    website="",
                ),
                PartyMembership(
                    person_id=10,
                    org_id=2,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 7, 28),
                    end_date=date(2026, 7, 27),
                ),
                ChamberMembership(
                    person_id=10,
                    org_id=1,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 7, 28),
                    end_date=date(2026, 7, 27),
                    condicion="Activo",
                    votes_in_election=12345,
                    dist_electoral="Tacna",
                ),
                ChamberMembership(
                    person_id=11,
                    org_id=1,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 7, 28),
                    end_date=date(2026, 7, 27),
                    condicion="Activo",
                    votes_in_election=100,
                    dist_electoral="Lima",
                ),
                Bill(
                    id="2021_14864",
                    pley_id="14864/2025-CR",
                    title="Proyecto Test",
                    summary_congreso="Resumen Congreso",
                    observations="",
                    status="Presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=10,
                    bill_approved=False,
                    summary_oc="Resumen OC",
                ),
                Bill(
                    id="2021_14865",
                    pley_id="14865/2025-CR",
                    title="Proyecto Aprobado",
                    summary_congreso="Resumen Congreso",
                    observations="",
                    status="Aprobado",
                    proponent=Proponents.CONGRESO,
                    author_id=10,
                    bill_approved=True,
                    summary_oc="Resumen OC",
                ),
                BillOrganization(
                    bill_id="2021_14864",
                    org_id=3,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=date(2025, 7, 22),
                    decision_date=None,
                ),
                BillOrganization(
                    bill_id="2021_14865",
                    org_id=3,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=date(2025, 7, 23),
                    decision_date=None,
                ),
                BillStep(
                    bill_id="2021_14864",
                    step_id=1,
                    step_type=TypeBillStep.PRESENTADO,
                    vote_step=False,
                    vote_event_id=None,
                    step_date=date(2025, 7, 22),
                    step_detail="Presentado",
                ),
                BillStep(
                    bill_id="2021_14864",
                    step_id=2,
                    step_type=TypeBillStep.EN_COMISION,
                    vote_step=False,
                    vote_event_id=None,
                    step_date=date(2025, 7, 23),
                    step_detail="En comisiÃ³n",
                ),
                Ley(id="12345", title="Ley Test", bill_id="2021_14865"),
            ]
        )
        db.commit()
