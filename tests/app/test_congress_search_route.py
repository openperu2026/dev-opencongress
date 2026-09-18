from __future__ import annotations

from datetime import date
import unicodedata

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.core.enums import Proponents, TypeCommittee, TypeOrganization
from backend.database.models import (
    Base,
    BancadaMembership,
    Bill,
    BillOrganization,
    ChamberMembership,
    CommitteeMembership,
    Congresista,
    Organization,
    PartyMembership,
)


def _register_unaccent(engine):
    @event.listens_for(engine, "connect")
    def _unaccent_on_connect(dbapi_connection, connection_record):
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
def session_factory(tmp_path):
    db_path = tmp_path / "processed_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    _register_unaccent(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


@pytest.fixture()
def client(monkeypatch, session_factory):
    import app.routes.congress as congress_module
    from app.app import create_app

    monkeypatch.setattr(congress_module, "SessionProcessed", session_factory)
    flask_app = create_app()
    flask_app.testing = True
    return flask_app.test_client()


def _seed_congress_search_data(session_factory) -> None:
    with session_factory() as db:
        db.add_all(
            [
                Congresista(
                    id=1,
                    full_name="Ana Perez",
                    first_name="Ana",
                    last_name="Perez",
                    dni="00000001",
                    gender="F",
                    photo_url="",
                    website="",
                ),
                Congresista(
                    id=2,
                    full_name="Beatriz Gomez",
                    first_name="Beatriz",
                    last_name="Gomez",
                    dni="00000002",
                    gender="F",
                    photo_url="",
                    website="",
                ),
                Organization(
                    org_id=1,
                    org_name="Comisión de Economía",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=2,
                    org_name="Comisión de Justicia",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=4,
                    org_name="Comisión Especial de Test",
                    org_short_name="Special Test",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ESP,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=3,
                    org_name="Partido Verde",
                    org_type=TypeOrganization.PARTY,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=6,
                    org_name="Bancada Verde",
                    org_type=TypeOrganization.BANCADA,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=5,
                    org_name="Congreso de la República",
                    org_type=TypeOrganization.CHAMBER,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                PartyMembership(
                    person_id=1,
                    org_id=3,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 1, 1),
                    end_date=date(2026, 12, 31),
                ),
                BancadaMembership(
                    person_id=1,
                    org_id=6,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 1, 1),
                    end_date=date(2026, 12, 31),
                ),
                CommitteeMembership(
                    person_id=1,
                    org_id=1,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 1, 1),
                    end_date=date(2026, 12, 31),
                ),
                CommitteeMembership(
                    person_id=2,
                    org_id=2,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 1, 1),
                    end_date=date(2026, 12, 31),
                ),
                CommitteeMembership(
                    person_id=2,
                    org_id=4,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 1, 1),
                    end_date=date(2026, 12, 31),
                ),
                ChamberMembership(
                    person_id=1,
                    org_id=5,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 1, 1),
                    end_date=date(2026, 12, 31),
                    condicion=None,
                    votes_in_election=1000,
                    dist_electoral="Lima",
                ),
                ChamberMembership(
                    person_id=2,
                    org_id=5,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 1, 1),
                    end_date=date(2026, 12, 31),
                    condicion=None,
                    votes_in_election=None,
                    dist_electoral="Cusco",
                ),
            ]
        )
        db.commit()


def test_search_form_uses_selects_for_bancada_and_commission(client):
    response = client.get("/congress")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<select name="bancada_q" id="bancada_q">' in body
    assert '<select name="region_q" id="region_q">' in body
    assert '<select name="commission_q" id="commission_q">' in body
    assert '<select name="special_committee_q" id="special_committee_q">' in body
    # The <select> itself must not carry a stray value= attribute (selection
    # happens via `selected` on its <option>s) -- hidden inputs replicating
    # these same filters onto the tab/pagination forms are expected and fine.
    assert '<select name="bancada_q" id="bancada_q" value=' not in body
    assert '<select name="region_q" id="region_q" value=' not in body
    assert '<select name="commission_q" id="commission_q" value=' not in body
    assert (
        '<select name="special_committee_q" id="special_committee_q" value=' not in body
    )
    # New labels for fix (f) -- must not be placeholder-as-label
    assert '<label for="bancada_q">' in body
    assert '<label for="region_q">' in body
    assert '<label for="commission_q">' in body
    assert '<label for="special_committee_q">' in body
    assert '<label for="name_q">' in body


def test_search_form_moves_committees_into_advanced_search(client):
    response = client.get("/congress")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    advanced_start = body.index('<details class="advanced-search"')
    advanced_end = body.index("</details>", advanced_start)
    advanced_section = body[advanced_start:advanced_end]
    assert '<select name="commission_q"' in advanced_section
    assert '<select name="special_committee_q"' in advanced_section
    # The primary row (before advanced-search) must NOT contain the visible
    # <select> fields anymore -- hidden inputs replicating these filters onto
    # the tab/pagination forms earlier in the page are expected and fine.
    assert '<select name="commission_q"' not in body[:advanced_start]
    assert '<select name="special_committee_q"' not in body[:advanced_start]


def test_search_filters_by_selected_bancada(client, session_factory):
    _seed_congress_search_data(session_factory)

    response = client.get(
        "/congress",
        query_string={"bancada_q": "Bancada Verde", "leg_period_q": "2021-2026"},
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Ana Perez" in body
    assert "Beatriz Gomez" not in body
    assert "Bancada: Bancada Verde" in body


def test_search_shows_all_congresistas_by_default(client, session_factory):
    _seed_congress_search_data(session_factory)

    response = client.get("/congress", query_string={"leg_period_q": "2021-2026"})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Ana Perez" in body
    assert "Beatriz Gomez" in body
    assert 'class="congress-mosaic-card"' in body
    assert "/congress/1/photo" in body
    assert "/congress/2/photo" in body


def test_congress_photo_prefers_stored_db_bytes(client, session_factory):
    _seed_congress_search_data(session_factory)
    image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 16

    with session_factory() as db:
        congresista = db.get(Congresista, 1)
        congresista.photo_url = "https://example.com/external.jpg"
        congresista.photo_bytes = image_bytes
        db.commit()

    response = client.get("/congress/1/photo")

    assert response.status_code == 200
    assert response.content_type == "image/jpeg"
    assert response.data == image_bytes


def test_search_filters_by_selected_region(client, session_factory):
    _seed_congress_search_data(session_factory)

    response = client.get(
        "/congress",
        query_string={"region_q": "Lima", "leg_period_q": "2021-2026"},
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Ana Perez" in body
    assert "Beatriz Gomez" not in body
    assert "Región: Lima" in body


def test_search_filters_by_selected_commission(client, session_factory):
    _seed_congress_search_data(session_factory)

    response = client.get(
        "/congress",
        query_string={
            "commission_q": "Comisión de Economía",
            "leg_period_q": "2021-2026",
        },
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Ana Perez" in body
    assert "Beatriz Gomez" not in body
    assert "Comisión: Comisión de Economía" in body


def test_search_filters_by_selected_special_committee(client, session_factory):
    _seed_congress_search_data(session_factory)

    response = client.get(
        "/congress",
        query_string={
            "special_committee_q": "Special Test",
            "leg_period_q": "2021-2026",
        },
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Ana Perez" not in body
    assert "Beatriz Gomez" in body
    assert "Comisión especial: Special Test" in body


def test_congress_detail_shows_bill_pley_id(client, session_factory):
    _seed_congress_search_data(session_factory)

    with session_factory() as db:
        db.add_all(
            [
                Bill(
                    id="2021_0001",
                    pley_id="0001/2021-CR",
                    title="Bill with visible pley id",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=1,
                    bill_approved=False,
                    summary_oc="",
                ),
                BillOrganization(
                    bill_id="2021_0001",
                    org_id=1,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=date(2024, 1, 10),
                    decision_date=None,
                ),
            ]
        )
        db.commit()

    response = client.get("/congress/1")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "0001/2021-CR" in body
    assert "Bill with visible pley id" in body


def _seed_bicameral_congress_data(session_factory) -> None:
    with session_factory() as db:
        db.add_all(
            [
                Congresista(
                    id=100,
                    full_name="Senadora Test",
                    first_name="Senadora",
                    last_name="Test",
                    dni="00000100",
                    gender="F",
                    photo_url="",
                    website="",
                ),
                Congresista(
                    id=101,
                    full_name="Diputado Test",
                    first_name="Diputado",
                    last_name="Test",
                    dni="00000101",
                    gender="M",
                    photo_url="",
                    website="",
                ),
                Organization(
                    org_id=200,
                    org_name="Senado de la República",
                    org_type=TypeOrganization.CHAMBER,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=201,
                    org_name="Cámara de Diputados",
                    org_type=TypeOrganization.CHAMBER,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                # Senadora Test was a Diputada in the legacy term, then a
                # Senadora in the new term -- this must never cross-match.
                ChamberMembership(
                    person_id=100,
                    org_id=201,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 1, 1),
                    end_date=date(2026, 7, 27),
                    condicion=None,
                    votes_in_election=500,
                    dist_electoral="Lima",
                ),
                ChamberMembership(
                    person_id=100,
                    org_id=200,
                    leg_period="2026-2031",
                    role="member",
                    start_date=date(2026, 7, 28),
                    end_date=date(2031, 7, 27),
                    condicion=None,
                    votes_in_election=800,
                    dist_electoral="Lima",
                ),
                ChamberMembership(
                    person_id=101,
                    org_id=201,
                    leg_period="2026-2031",
                    role="member",
                    start_date=date(2026, 7, 28),
                    end_date=date(2031, 7, 27),
                    condicion=None,
                    votes_in_election=900,
                    dist_electoral="Cusco",
                ),
            ]
        )
        db.commit()


def test_chamber_and_period_combined_filter_does_not_cross_match(
    client, session_factory
):
    """CRITICAL regression: a person who held a different chamber in a
    different period must not match a chamber+period combination they never
    actually held (e.g. Diputada 2021-2026 + Senadora 2026-2031)."""
    _seed_bicameral_congress_data(session_factory)

    body = client.get(
        "/congress",
        query_string={"chamber_q": "diputados", "leg_period_q": "2026-2031"},
    ).get_data(as_text=True)

    assert "Senadora Test" not in body
    assert "Diputado Test" in body

    body_senado = client.get(
        "/congress",
        query_string={"chamber_q": "senado", "leg_period_q": "2026-2031"},
    ).get_data(as_text=True)
    assert "Senadora Test" in body_senado
    assert "Diputado Test" not in body_senado


def test_org_id_not_hardcoded_regression(client, session_factory):
    """CRITICAL regression: the previous hardcoded ChamberMembership.org_id
    == 1 bug must not resurface -- a person whose chamber org_id is not 1
    (here, 200/201) still resolves district/condicion/votes on the detail
    page instead of silently falling back to 'No disponible'/None/0."""
    _seed_bicameral_congress_data(session_factory)

    body = client.get("/congress/101").get_data(as_text=True)

    assert "Cusco" in body


def test_unfiltered_congress_is_period_scoped(client, session_factory):
    """Closes UX High issue (c): an unfiltered visit must not return the
    full historical roster across all periods."""
    _seed_bicameral_congress_data(session_factory)

    default_body = client.get("/congress").get_data(as_text=True)
    assert "Senadora Test" in default_body
    assert "Diputado Test" in default_body

    legacy_body = client.get(
        "/congress", query_string={"leg_period_q": "2021-2026"}
    ).get_data(as_text=True)
    assert "Senadora Test" in legacy_body
    assert "Diputado Test" not in legacy_body


def test_congress_detail_non_numeric_id_returns_404(client):
    """CRITICAL regression: fix (e) -- Flask's <int:> converter must 404 a
    non-numeric id instead of raising an unhandled ValueError."""
    response = client.get("/congress/abc")

    assert response.status_code == 404


def test_congress_pagination(client, session_factory):
    with session_factory() as db:
        db.add(
            Organization(
                org_id=300,
                org_name="Senado de la República",
                org_type=TypeOrganization.CHAMBER,
                org_subtype=None,
                org_link=None,
                parent_org_id=None,
                date_founding=None,
                date_dissolution=None,
            )
        )
        for i in range(1, 61):
            db.add(
                Congresista(
                    id=1000 + i,
                    full_name=f"Pag Congresista {i:03d}",
                    first_name="Pag",
                    last_name=f"Congresista {i:03d}",
                    dni=f"P{i:08d}",
                    gender="F",
                    photo_url="",
                    website="",
                )
            )
            db.add(
                ChamberMembership(
                    person_id=1000 + i,
                    org_id=300,
                    leg_period="2026-2031",
                    role="member",
                    start_date=date(2026, 7, 28),
                    end_date=date(2031, 7, 27),
                    condicion=None,
                    votes_in_election=1,
                    dist_electoral="Lima",
                )
            )
        db.commit()

    first_page = client.get("/congress").get_data(as_text=True)
    assert "Pag Congresista 001" in first_page
    assert "Pag Congresista 050" in first_page
    assert "Pag Congresista 051" not in first_page

    second_page = client.get("/congress", query_string={"page": 2}).get_data(
        as_text=True
    )
    assert "Pag Congresista 051" in second_page
    assert "Pag Congresista 060" in second_page
    assert "Pag Congresista 001" not in second_page


def test_chamber_badge_renders_on_mosaic_and_detail(client, session_factory):
    _seed_bicameral_congress_data(session_factory)

    body = client.get("/congress", query_string={"leg_period_q": "2026-2031"}).get_data(
        as_text=True
    )
    assert "chamber-badge--senado" in body
    assert "chamber-badge--diputados" in body

    detail_body = client.get("/congress/100").get_data(as_text=True)
    assert "chamber-badge--senado" in detail_body


def test_chamber_selector_hidden_for_legacy_period(client):
    legacy_body = client.get(
        "/congress", query_string={"leg_period_q": "2021-2026"}
    ).get_data(as_text=True)
    assert 'class="chamber-tabs"' not in legacy_body

    modern_body = client.get(
        "/congress", query_string={"leg_period_q": "2026-2031"}
    ).get_data(as_text=True)
    assert 'class="chamber-tabs"' in modern_body


def test_legacy_period_clears_a_carried_over_chamber_filter(client, session_factory):
    """Changing to the unicameral period must discard a stale chamber tab."""
    _seed_bicameral_congress_data(session_factory)

    body = client.post(
        "/congress",
        data={"leg_period_q": "2021-2026", "chamber_q": "diputados"},
    ).get_data(as_text=True)

    assert "Senadora Test" in body
    assert '<input type="hidden" name="chamber_q" value="">' in body


def _seed_reelected_congresista(session_factory) -> None:
    with session_factory() as db:
        db.add_all(
            [
                Congresista(
                    id=200,
                    full_name="Rosa Huamán Torres",
                    first_name="Rosa",
                    last_name="Huamán Torres",
                    dni="00000200",
                    gender="F",
                    photo_url="",
                    website="",
                ),
                Organization(
                    org_id=210,
                    org_name="Cámara de Diputados",
                    org_type=TypeOrganization.CHAMBER,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=211,
                    org_name="Senado de la República",
                    org_type=TypeOrganization.CHAMBER,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=212,
                    org_name="Renovación Popular",
                    org_type=TypeOrganization.PARTY,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=213,
                    org_name="Fuerza Popular",
                    org_type=TypeOrganization.PARTY,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=214,
                    org_name="Comisión de Economía",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=215,
                    org_name="Comisión de Constitución",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD_LEG,
                    org_link=None,
                    parent_org_id=211,
                    date_founding=None,
                    date_dissolution=None,
                ),
                ChamberMembership(
                    person_id=200,
                    org_id=210,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 7, 28),
                    end_date=date(2026, 7, 27),
                    condicion=None,
                    votes_in_election=31860,
                    dist_electoral="Lima",
                ),
                ChamberMembership(
                    person_id=200,
                    org_id=211,
                    leg_period="2026-2031",
                    role="member",
                    start_date=date(2026, 7, 28),
                    end_date=date(2031, 7, 27),
                    condicion="En Ejercicio",
                    votes_in_election=48120,
                    dist_electoral="Lima",
                ),
                PartyMembership(
                    person_id=200,
                    org_id=212,
                    leg_period="2021-2026",
                    role="member",
                    start_date=date(2021, 7, 28),
                    end_date=date(2026, 7, 27),
                ),
                PartyMembership(
                    person_id=200,
                    org_id=213,
                    leg_period="2026-2031",
                    role="member",
                    start_date=date(2026, 7, 28),
                    end_date=date(2031, 7, 27),
                ),
                CommitteeMembership(
                    person_id=200,
                    org_id=214,
                    leg_period="2021-2026",
                    role="Miembro",
                    start_date=date(2021, 7, 28),
                    end_date=date(2026, 7, 27),
                ),
                CommitteeMembership(
                    person_id=200,
                    org_id=215,
                    leg_period="2026-2031",
                    role="Miembro",
                    start_date=date(2026, 7, 28),
                    end_date=date(2031, 7, 27),
                ),
                Bill(
                    id="2021_7001",
                    title="Bill from legacy term",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=200,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="2021_7001",
                ),
                Bill(
                    id="00007-2026-2031-S",
                    title="Bill from new term",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=200,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="00007-2026-2031-S",
                ),
                BillOrganization(
                    bill_id="2021_7001",
                    org_id=214,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=date(2024, 6, 1),
                    decision_date=None,
                ),
                BillOrganization(
                    bill_id="00007-2026-2031-S",
                    org_id=215,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=date(2026, 8, 1),
                    decision_date=None,
                ),
            ]
        )
        db.commit()


def test_detail_shows_period_tabs_for_reelected_person(client, session_factory):
    _seed_reelected_congresista(session_factory)

    body = client.get("/congress/200").get_data(as_text=True)

    assert "2026 - 2031" in body
    assert "2021 - 2026" in body
    assert '<nav class="period-tabs"' in body


def test_detail_no_tabs_for_single_period_person(client, session_factory):
    _seed_congress_search_data(session_factory)

    body = client.get("/congress/1").get_data(as_text=True)

    assert '<nav class="period-tabs"' not in body


def test_detail_defaults_to_most_recent_period(client, session_factory):
    _seed_reelected_congresista(session_factory)

    body = client.get("/congress/200").get_data(as_text=True)

    assert "Fuerza Popular" in body
    assert "chamber-badge--senado" in body
    assert "Comisión de Constitución" in body
    assert "Renovación Popular" not in body


def test_detail_switching_period_scopes_header_committees_and_bills(
    client, session_factory
):
    _seed_reelected_congresista(session_factory)

    body = client.get(
        "/congress/200", query_string={"leg_period_q": "2021-2026"}
    ).get_data(as_text=True)

    assert "Renovación Popular" in body
    assert "chamber-badge--diputados" in body
    assert "Comisión de Economía" in body
    assert "Comisión de Constitución" not in body
    # CRITICAL: bill stats scoped to the selected period too
    assert "Bill from legacy term" in body
    assert "Bill from new term" not in body


def test_detail_invalid_period_falls_back_to_most_recent(client, session_factory):
    _seed_reelected_congresista(session_factory)

    response = client.get("/congress/200", query_string={"leg_period_q": "1995-2000"})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Fuerza Popular" in body


def test_search_to_detail_link_carries_period(client, session_factory):
    """The mosaic card is a POST form (no query string) carrying the
    search's active period as a hidden input into the detail route."""
    _seed_reelected_congresista(session_factory)

    search_body = client.get(
        "/congress", query_string={"leg_period_q": "2021-2026"}
    ).get_data(as_text=True)
    assert (
        'action="/congress/200"' in search_body
        and '<input type="hidden" name="leg_period_q" value="2021-2026">' in search_body
    )

    # Simulate submitting that exact hidden form.
    posted_detail_body = client.post(
        "/congress/200", data={"leg_period_q": "2021-2026"}
    ).get_data(as_text=True)
    assert "Renovación Popular" in posted_detail_body


def test_detail_condicion_shows_no_disponible_instead_of_none(client, session_factory):
    """Regression: the 2021-2026 ChamberMembership row has condicion=None;
    the detail page must show 'No disponible', not the literal 'None'."""
    _seed_reelected_congresista(session_factory)

    body = client.get(
        "/congress/200", query_string={"leg_period_q": "2021-2026"}
    ).get_data(as_text=True)

    assert "No disponible" in body


def test_detail_committee_membership_shows_start_and_end_dates(client, session_factory):
    _seed_reelected_congresista(session_factory)

    body = client.get(
        "/congress/200", query_string={"leg_period_q": "2026-2031"}
    ).get_data(as_text=True)

    assert "jul 2026" in body
    assert "jul 2031" in body


def test_main_search_form_submits_via_post_with_no_query_string(
    client, session_factory
):
    """The core ask: filters must not appear in the URL. The search form
    itself posts to a bare /congress action -- no query string involved at
    all, with or without JS."""
    _seed_congress_search_data(session_factory)

    response = client.post(
        "/congress", data={"name_q": "Ana", "leg_period_q": "2021-2026"}
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'method="post"' in body
    assert "Ana Perez" in body
    assert "Beatriz Gomez" not in body


def test_period_tab_is_a_post_form_not_a_link(client, session_factory):
    """Tabs/pagination/mosaic-card links must never be plain GET links with
    a query string -- they're POST forms with hidden inputs."""
    _seed_reelected_congresista(session_factory)

    body = client.get("/congress", query_string={"leg_period_q": "2026-2031"}).get_data(
        as_text=True
    )

    assert 'href="/congress?' not in body
    assert '<form method="post" action="/congress"' in body
    assert '<input type="hidden" name="leg_period_q" value="2021-2026">' in body

    # Simulate actually clicking the "2021-2026" tab.
    switched = client.post("/congress", data={"leg_period_q": "2021-2026"}).get_data(
        as_text=True
    )
    assert "Rosa Huamán Torres" in switched
