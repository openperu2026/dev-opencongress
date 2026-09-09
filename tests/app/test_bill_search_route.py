from __future__ import annotations

from datetime import date as real_date
import unicodedata

from backend.core.enums import Proponents
from backend.core.enums import TypeBillStep, TypeCommittee, TypeOrganization
from backend.database.models import (
    Base,
    Bill,
    BillOrganization,
    BillStep,
    CommitteeMembership,
    Congresista,
    Ley,
    PartyMembership,
    Organization,
)

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


class FixedDate(real_date):
    @classmethod
    def today(cls):
        return cls(2026, 5, 24)


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
    import app.routes.bills as bills_module
    from app.app import create_app

    monkeypatch.setattr(bills_module, "SessionProcessed", session_factory)
    monkeypatch.setattr(bills_module, "date", FixedDate)
    bills_module._get_query_spellchecker.cache_clear()
    flask_app = create_app()
    flask_app.testing = True
    return flask_app.test_client()


def _seed_bills(session_factory, count: int) -> None:
    with session_factory() as db:
        db.add(
            Organization(
                org_id=900,
                org_name="Comisión Generica de Test",
                org_type=TypeOrganization.COMMITTEE,
                org_subtype=TypeCommittee.COM_ORD,
                org_link=None,
                parent_org_id=None,
                date_founding=None,
                date_dissolution=None,
            )
        )
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
                    pley_id=f"2021_{index:04d}",
                )
            )
            db.add(
                BillOrganization(
                    bill_id=f"2021_{index:04d}",
                    org_id=900,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=real_date(2024, 1, 1),
                    decision_date=None,
                )
            )
        db.commit()


def _seed_bill_search_data(session_factory) -> None:
    with session_factory() as db:
        db.add_all(
            [
                Bill(
                    id="2021_0001",
                    title="Bill 0001",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=1,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="2021_0001",
                    bill_diff=True,
                ),
                Bill(
                    id="2021_0002",
                    title="Bill 0002",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=2,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="2021_0002",
                ),
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
                PartyMembership(
                    person_id=1,
                    org_id=3,
                    leg_period="2021-2026",
                    role="member",
                    start_date=real_date(2021, 1, 1),
                    end_date=real_date(2026, 12, 31),
                ),
                CommitteeMembership(
                    person_id=1,
                    org_id=1,
                    leg_period="2021-2026",
                    role="member",
                    start_date=real_date(2021, 1, 1),
                    end_date=real_date(2026, 12, 31),
                ),
                BillStep(
                    bill_id="2021_0001",
                    step_id=1,
                    step_type=TypeBillStep.PRESENTADO,
                    vote_step=False,
                    vote_event_id=None,
                    step_date=real_date(2024, 1, 1),
                    step_detail="",
                ),
                BillStep(
                    bill_id="2021_0001",
                    step_id=2,
                    step_type=TypeBillStep.VOTACION,
                    vote_step=False,
                    vote_event_id=None,
                    step_date=real_date(2024, 1, 15),
                    step_detail="",
                ),
                BillStep(
                    bill_id="2021_0002",
                    step_id=1,
                    step_type=TypeBillStep.ARCHIVADO,
                    vote_step=False,
                    vote_event_id=None,
                    step_date=real_date(2024, 2, 1),
                    step_detail="",
                ),
                BillOrganization(
                    bill_id="2021_0001",
                    org_id=1,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=real_date(2024, 1, 10),
                    decision_date=None,
                ),
                BillOrganization(
                    bill_id="2021_0002",
                    org_id=2,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=real_date(2024, 2, 10),
                    decision_date=None,
                ),
                Bill(
                    id="2021_0003",
                    title="Bill 0003",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=1,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="2021_0003",
                ),
                BillOrganization(
                    bill_id="2021_0003",
                    org_id=4,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=real_date(2025, 5, 1),
                    decision_date=None,
                ),
                Ley(id="L-001", title="Ley 1", bill_id="2021_0001"),
                Ley(id="L-002", title="Ley 2", bill_id="2021_0002"),
            ]
        )
        db.commit()


def test_search_results_are_paginated_by_50(client, session_factory):
    _seed_bills(session_factory, 55)

    first_page = client.get("/bills?title_q=Bill&leg_period_q=2021-2026")
    first_body = first_page.get_data(as_text=True)
    assert first_page.status_code == 200
    assert "Mostrando 1-50 de 55 proyectos de ley" in first_body
    assert "Bill 0001" in first_body
    assert "Bill 0050" in first_body
    assert "Bill 0051" not in first_body
    # Pagination is a hidden-input POST form now (no query string exposed) --
    # confirm the "page 2" control renders as a submit button, not a link.
    assert '<input type="hidden" name="page" value="2">' in first_body
    assert 'class="pagination-tab"' in first_body

    second_page = client.get("/bills?title_q=Bill&page=2&leg_period_q=2021-2026")
    second_body = second_page.get_data(as_text=True)
    assert second_page.status_code == 200
    assert "Mostrando 51-55 de 55 proyectos de ley" in second_body
    assert "Bill 0051" in second_body
    assert "Bill 0055" in second_body
    assert "Bill 0001" not in second_body
    assert '<input type="hidden" name="page" value="1">' in second_body
    assert 'class="pagination-prev"' in second_body


def test_search_results_cap_at_500_plus(client, session_factory):
    _seed_bills(session_factory, 501)

    first_page = client.get("/bills?title_q=Bill&leg_period_q=2021-2026")
    body = first_page.get_data(as_text=True)

    assert first_page.status_code == 200
    assert "Mostrando 1-50 de 500+ proyectos de ley" in body


def _seed_status_bills(db) -> None:
    db.add_all(
        [
            Organization(
                org_id=901,
                org_name="Comisión Status Test",
                org_type=TypeOrganization.COMMITTEE,
                org_subtype=TypeCommittee.COM_ORD,
                org_link=None,
                parent_org_id=None,
                date_founding=None,
                date_dissolution=None,
            ),
            Bill(
                id="2021_9001",
                title="Approved bill",
                summary_congreso="",
                observations="",
                status="presentado",
                proponent=Proponents.CONGRESO,
                bill_approved=True,
                summary_oc="",
                pley_id="2021_9001",
            ),
            Bill(
                id="2021_9002",
                title="Not approved bill",
                summary_congreso="",
                observations="",
                status="presentado",
                proponent=Proponents.CONGRESO,
                bill_approved=False,
                summary_oc="",
                pley_id="2021_9002",
            ),
            BillOrganization(
                bill_id="2021_9001",
                org_id=901,
                org_type=TypeOrganization.COMMITTEE,
                presentation_date=real_date(2024, 1, 1),
                decision_date=None,
            ),
            BillOrganization(
                bill_id="2021_9002",
                org_id=901,
                org_type=TypeOrganization.COMMITTEE,
                presentation_date=real_date(2024, 1, 1),
                decision_date=None,
            ),
        ]
    )
    db.commit()


def test_search_filters_by_status_approved_alone(client, session_factory):
    with session_factory() as db:
        _seed_status_bills(db)

    response = client.get(
        "/bills", query_string={"status": "approved", "leg_period_q": "2021-2026"}
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Mostrando" in body
    assert "Approved bill" in body
    assert "Not approved bill" not in body


def test_search_filters_by_status_not_approved_alone(client, session_factory):
    with session_factory() as db:
        _seed_status_bills(db)

    response = client.get(
        "/bills", query_string={"status": "not-approved", "leg_period_q": "2021-2026"}
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Mostrando" in body
    assert "Not approved bill" in body
    assert "Approved bill" not in body


def test_status_all_does_not_force_search_path(client, session_factory):
    _seed_bill_search_data(session_factory)

    response = client.get("/bills?status=all&leg_period_q=2021-2026")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Mostrando" not in body
    assert "Bill 0001" in body


def test_footer_contact_link_points_to_contact_section(client):
    response = client.get("/bills")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<a href="/#contact">' in body
    assert '<a href="#">' not in body


def test_search_form_includes_new_filters(client):
    response = client.get("/bills")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Busca el proyecto de ley por:" in body
    assert 'name="pley_id_q"' in body
    assert 'name="law_id_q"' in body
    assert 'name="current_step_q"' in body
    assert 'placeholder="dd/mm/aaaa"' in body
    assert 'name="presentation_date_from"' in body
    assert 'name="presentation_date_to"' in body
    assert 'name="presentation_date_from_year"' in body
    assert 'name="presentation_date_from_month"' in body
    assert 'name="presentation_date_from_day"' in body
    assert 'name="presentation_date_to_year"' in body
    assert 'name="presentation_date_to_month"' in body
    assert 'name="presentation_date_to_day"' in body
    assert 'name="author_party_q"' in body
    assert 'name="organization_name_q"' in body
    assert 'name="special_committee_q"' in body
    assert 'name="bill_diff_q"' in body
    assert "Tiene diferencia de versiones" in body
    assert 'value="yes"' in body
    assert 'value="no"' in body
    assert "Fecha de presentación" in body
    assert "Desde" in body
    assert "Hasta" in body
    assert "Partido del autor" in body
    assert 'name="presentation_date_from_year"' in body and 'value="" selected' in body
    assert 'name="presentation_date_from_month"' in body and 'value="" selected' in body
    assert 'name="presentation_date_from_day"' in body and 'value="" selected' in body
    assert 'name="presentation_date_to_year"' in body and 'value="" selected' in body
    assert 'name="presentation_date_to_month"' in body and 'value="" selected' in body
    assert 'name="presentation_date_to_day"' in body and 'value="" selected' in body


def test_search_filters_by_native_date_inputs(client, session_factory):
    _seed_bill_search_data(session_factory)

    response = client.get(
        "/bills",
        query_string={
            "presentation_date_from": "2024-01-10",
            "presentation_date_to": "2024-01-31",
            "leg_period_q": "2021-2026",
        },
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "2021_0001" in body
    assert "2021_0002" not in body
    assert 'name="presentation_date_from"' in body
    assert 'value="2024-01-10"' in body
    assert "2024-01-10 - 2024-01-31" in body


def test_search_form_can_render_in_english(client):
    response = client.get("/bills?lang=en")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<html lang="en">' in body
    assert "Search the bill by:" in body
    assert "Presentation Date" in body
    assert "Author party" in body
    assert 'placeholder="General search..."' in body
    assert 'placeholder="Búsqueda general..."' not in body


def test_recent_bills_falls_back_to_proponent_when_author_is_missing(
    client, session_factory
):
    with session_factory() as db:
        db.add_all(
            [
                Bill(
                    id="2021_0100",
                    title="Bill without author",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=None,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="0100/2021-CR",
                ),
                Organization(
                    org_id=100,
                    org_name="Comisión Test",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                BillOrganization(
                    bill_id="2021_0100",
                    org_id=100,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=real_date(2026, 8, 1),
                    decision_date=None,
                ),
            ]
        )
        db.commit()

    response = client.get("/bills")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Bill without author" in body
    assert Proponents.CONGRESO.value in body


def test_searched_results_fall_back_to_proponent_when_author_is_missing(
    client, session_factory
):
    with session_factory() as db:
        db.add_all(
            [
                Bill(
                    id="2021_0200",
                    title="Searchable bill without author",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=None,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="0200/2021-CR",
                ),
                Organization(
                    org_id=200,
                    org_name="Comisión Test 200",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                BillOrganization(
                    bill_id="2021_0200",
                    org_id=200,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=real_date(2024, 3, 1),
                    decision_date=None,
                ),
            ]
        )
        db.commit()

    response = client.get("/bills?title_q=Searchable&leg_period_q=2021-2026")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Searchable bill without author" in body
    assert Proponents.CONGRESO.value in body
    assert "None" not in body


def test_search_filters_by_bill_diff(client, session_factory):
    _seed_bill_search_data(session_factory)

    yes_response = client.get(
        "/bills", query_string={"bill_diff_q": "yes", "leg_period_q": "2021-2026"}
    )
    yes_body = yes_response.get_data(as_text=True)

    assert yes_response.status_code == 200
    assert "Mostrando 1-1 de 1 proyectos de ley" in yes_body
    assert "2021_0001" in yes_body
    assert "2021_0002" not in yes_body

    no_response = client.get(
        "/bills", query_string={"bill_diff_q": "no", "leg_period_q": "2021-2026"}
    )
    no_body = no_response.get_data(as_text=True)

    assert no_response.status_code == 200
    assert "2021_0002" in no_body
    assert "2021_0003" in no_body
    assert "2021_0001" not in no_body


def test_search_filters_bill_id_law_id_step_date_and_committee(client, session_factory):
    _seed_bill_search_data(session_factory)

    response = client.get(
        "/bills",
        query_string={
            "pley_id_q": "2021_0001",
            "law_id_q": "L-001",
            "current_step_q": TypeBillStep.VOTACION.value,
            "author_party_q": "Partido Verde",
            "presentation_date_from_year": 2024,
            "presentation_date_from_month": 1,
            "presentation_date_from_day": 1,
            "presentation_date_to_year": 2024,
            "presentation_date_to_month": 1,
            "presentation_date_to_day": 31,
            "organization_name_q": "Comisión de Economía",
            "leg_period_q": "2021-2026",
        },
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Mostrando 1-1 de 1 proyectos de ley" in body
    assert "2021_0001" in body
    assert "2021_0002" not in body
    assert "Número de la ley: L-001" in body
    assert "Etapa actual: Votación" in body
    assert "Partido del autor: Partido Verde" in body
    assert "2024-01-01 - 2024-01-31" in body


def test_search_filters_by_special_committee(client, session_factory):
    _seed_bill_search_data(session_factory)

    response = client.get(
        "/bills",
        query_string={
            "special_committee_q": "Special Test",
            "leg_period_q": "2021-2026",
        },
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Mostrando 1-1 de 1 proyectos de ley" in body
    assert "2021_0003" in body
    assert "2021_0001" not in body
    assert "Comisión especial: Special Test" in body


def test_search_ignores_spanish_accents_for_text_filters(client, session_factory):
    with session_factory() as db:
        db.add_all(
            [
                Congresista(
                    id=10,
                    full_name="José Álvarez",
                    first_name="José",
                    last_name="Álvarez",
                    dni="00000010",
                    gender="M",
                    photo_url="",
                    website="",
                ),
                Organization(
                    org_id=20,
                    org_name="Partido Perú",
                    org_type=TypeOrganization.PARTY,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Bill(
                    id="2021_0099",
                    title="Análisis del café",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=10,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="2021_0099",
                ),
                PartyMembership(
                    person_id=10,
                    org_id=20,
                    leg_period="2021-2026",
                    role="member",
                    start_date=real_date(2021, 1, 1),
                    end_date=real_date(2026, 12, 31),
                ),
                Organization(
                    org_id=21,
                    org_name="Comisión Accents Test",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                BillOrganization(
                    bill_id="2021_0099",
                    org_id=21,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=real_date(2024, 1, 1),
                    decision_date=None,
                ),
            ]
        )
        db.commit()

    response = client.get(
        "/bills",
        query_string={
            "title_q": "Analisis del cafe",
            "author_q": "Jose Alvarez",
            "leg_period_q": "2021-2026",
        },
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "2021_0099" in body
    assert "Análisis del café" in body
    assert "José Álvarez" in body


def test_date_picker_builds_valid_february_days_for_leap_year():
    import app.routes.bills as bills_module

    picker = bills_module._build_date_picker(
        "presentation_date_from",
        {
            "presentation_date_from_year": "2024",
            "presentation_date_from_month": "2",
            "presentation_date_from_day": "29",
        },
        FixedDate.today(),
    )

    assert picker["selected_date"] == real_date(2024, 2, 29)
    assert len(picker["day_options"]) == 29
    assert picker["day_options"][-1] == 29


def test_query_spellchecker_unions_dictionary_with_bill_titles(
    monkeypatch, session_factory
):
    import app.routes.bills as bills_module

    with session_factory() as db:
        db.add(
            Bill(
                id="2021_0200",
                title="Ley de Presupuesto Público",
                summary_congreso="",
                observations="",
                status="presentado",
                proponent=Proponents.CONGRESO,
                bill_approved=False,
                summary_oc="",
                pley_id="2021_0200",
            )
        )
        db.commit()

    monkeypatch.setattr(bills_module, "SessionProcessed", session_factory)
    bills_module._get_query_spellchecker.cache_clear()

    spell = bills_module._get_query_spellchecker()

    assert "presupuesto" in spell.known(["presupuesto"])
    assert "congreso" in spell.known(["congreso"])


def test_correct_token_fixes_general_dictionary_typo():
    import app.routes.bills as bills_module
    from spellchecker import SpellChecker

    spell = SpellChecker(language="es")

    assert bills_module._correct_token("congrezo", spell) == "congreso"


def test_correct_token_fixes_domain_word_typo_once_loaded():
    import app.routes.bills as bills_module
    from spellchecker import SpellChecker

    spell = SpellChecker(language="es")
    spell.word_frequency.load_words(["presupuesto"])

    assert bills_module._correct_token("presupuest", spell) == "presupuesto"


def test_correct_token_leaves_short_and_numeric_tokens_unchanged():
    import app.routes.bills as bills_module
    from spellchecker import SpellChecker

    spell = SpellChecker(language="es")

    assert bills_module._correct_token("paz", spell) == "paz"
    assert bills_module._correct_token("2021_0004", spell) == "2021_0004"


def test_correct_token_leaves_already_correct_word_unchanged():
    import app.routes.bills as bills_module
    from spellchecker import SpellChecker

    spell = SpellChecker(language="es")

    assert bills_module._correct_token("congreso", spell) == "congreso"


def test_correct_query_typos_preserves_structure(monkeypatch, session_factory):
    import app.routes.bills as bills_module

    monkeypatch.setattr(bills_module, "SessionProcessed", session_factory)
    bills_module._get_query_spellchecker.cache_clear()

    corrected = bills_module._correct_query_typos("proyecto de ley sobre el congrezo")

    assert corrected == "proyecto de ley sobre el congreso"


def test_search_semantic_bills_does_not_raise_nameerror(monkeypatch, session_factory):
    import app.routes.bills as bills_module
    from backend.database.crud import pipeline_embeddings

    monkeypatch.setattr(bills_module, "SessionProcessed", session_factory)
    bills_module._get_query_spellchecker.cache_clear()
    pipeline_embeddings._get_embedding_model.cache_clear()

    encode_calls = []

    class FakeModel:
        def encode(self, text, normalize_embeddings=True):
            encode_calls.append(text)
            return [0.0] * 768

    monkeypatch.setattr(
        pipeline_embeddings, "SentenceTransformer", lambda name, **kwargs: FakeModel()
    )

    class StubResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class StubDB:
        def execute(self, stmt):
            return StubResult()

    results = bills_module._search_semantic_bills(
        StubDB(), query="congrezo", embedding_model=None
    )

    assert results == []
    assert encode_calls == ["congreso"]


def _seed_bicameral_bills(session_factory) -> None:
    with session_factory() as db:
        db.add_all(
            [
                Organization(
                    org_id=500,
                    org_name="Senado de la República",
                    org_type=TypeOrganization.CHAMBER,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=501,
                    org_name="Cámara de Diputados",
                    org_type=TypeOrganization.CHAMBER,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=502,
                    org_name="Comisión de Economía",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=503,
                    org_name="Comisión de Economía",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD_LEG,
                    org_link=None,
                    parent_org_id=501,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Bill(
                    id="00001-2026-2031-S",
                    title="Senado Bill",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="00001-2026-2031-S",
                ),
                Bill(
                    id="00002-2026-2031-CD",
                    title="Diputados Bill",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="00002-2026-2031-CD",
                ),
                Bill(
                    id="2021_5001",
                    title="Legacy Bill",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="2021_5001",
                ),
                BillOrganization(
                    bill_id="00001-2026-2031-S",
                    org_id=500,
                    org_type=TypeOrganization.CHAMBER,
                    presentation_date=real_date(2026, 8, 1),
                    decision_date=None,
                ),
                BillOrganization(
                    bill_id="00002-2026-2031-CD",
                    org_id=501,
                    org_type=TypeOrganization.CHAMBER,
                    presentation_date=real_date(2026, 8, 2),
                    decision_date=None,
                ),
                BillOrganization(
                    bill_id="00002-2026-2031-CD",
                    org_id=503,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=real_date(2026, 8, 2),
                    decision_date=None,
                ),
                BillOrganization(
                    bill_id="2021_5001",
                    org_id=502,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=real_date(2024, 6, 1),
                    decision_date=None,
                ),
            ]
        )
        db.commit()


def test_chamber_filter_isolates_senado_and_diputados(client, session_factory):
    _seed_bicameral_bills(session_factory)

    senado_body = client.get(
        "/bills", query_string={"title_q": "Bill", "chamber_q": "senado"}
    ).get_data(as_text=True)
    assert "Senado Bill" in senado_body
    assert "Diputados Bill" not in senado_body

    diputados_body = client.get(
        "/bills", query_string={"title_q": "Bill", "chamber_q": "diputados"}
    ).get_data(as_text=True)
    assert "Diputados Bill" in diputados_body
    assert "Senado Bill" not in diputados_body

    both_body = client.get("/bills", query_string={"title_q": "Bill"}).get_data(
        as_text=True
    )
    assert "Senado Bill" in both_body
    assert "Diputados Bill" in both_body


def test_recent_bills_are_scoped_by_period(client, session_factory):
    _seed_bicameral_bills(session_factory)

    default_body = client.get("/bills").get_data(as_text=True)
    assert "Senado Bill" in default_body
    assert "Diputados Bill" in default_body
    assert "Legacy Bill" not in default_body

    legacy_body = client.get(
        "/bills", query_string={"leg_period_q": "2021-2026"}
    ).get_data(as_text=True)
    assert "Legacy Bill" in legacy_body
    assert "Senado Bill" not in legacy_body
    assert "Diputados Bill" not in legacy_body


def test_committee_filter_is_period_gated_regression(client, session_factory):
    """CRITICAL regression: a 2021-2026 committee-name search must not match
    a same-named 2026-2031 committee that carries the new COM_ORD_LEG
    subtype -- this is the exact self-contradiction the outside-voice pass
    caught in the first draft of the committee fix."""
    _seed_bicameral_bills(session_factory)

    body = client.get(
        "/bills",
        query_string={
            "organization_name_q": "Comisión de Economía",
            "leg_period_q": "2021-2026",
        },
    ).get_data(as_text=True)

    assert "Legacy Bill" in body
    assert "Diputados Bill" not in body


def test_semantic_search_failure_falls_back_gracefully(client, monkeypatch):
    import app.routes.bills as bills_module

    def _raise(*args, **kwargs):
        raise RuntimeError("embedding backend unavailable")

    monkeypatch.setattr(bills_module, "_search_semantic_bills", _raise)

    response = client.get("/bills", query_string={"semantic_query": "presupuesto"})

    assert response.status_code == 200


def test_author_party_q_actually_filters_results(client, session_factory):
    with session_factory() as db:
        db.add_all(
            [
                Congresista(
                    id=50,
                    full_name="Party Test Author",
                    first_name="Party",
                    last_name="Author",
                    dni="00000050",
                    gender="F",
                    photo_url="",
                    website="",
                ),
                Organization(
                    org_id=510,
                    org_name="Partido Naranja",
                    org_type=TypeOrganization.PARTY,
                    org_subtype=None,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                Organization(
                    org_id=511,
                    org_name="Comisión Party Test",
                    org_type=TypeOrganization.COMMITTEE,
                    org_subtype=TypeCommittee.COM_ORD,
                    org_link=None,
                    parent_org_id=None,
                    date_founding=None,
                    date_dissolution=None,
                ),
                PartyMembership(
                    person_id=50,
                    org_id=510,
                    leg_period="2021-2026",
                    role="member",
                    start_date=real_date(2021, 1, 1),
                    end_date=real_date(2026, 12, 31),
                ),
                Bill(
                    id="2021_6001",
                    title="Bill by Naranja author",
                    summary_congreso="",
                    observations="",
                    status="presentado",
                    proponent=Proponents.CONGRESO,
                    author_id=50,
                    bill_approved=False,
                    summary_oc="",
                    pley_id="2021_6001",
                ),
                BillOrganization(
                    bill_id="2021_6001",
                    org_id=511,
                    org_type=TypeOrganization.COMMITTEE,
                    presentation_date=real_date(2024, 6, 1),
                    decision_date=None,
                ),
            ]
        )
        db.commit()

    matching = client.get(
        "/bills",
        query_string={
            "author_party_q": "Partido Naranja",
            "leg_period_q": "2021-2026",
        },
    ).get_data(as_text=True)
    assert "Bill by Naranja author" in matching

    non_matching = client.get(
        "/bills",
        query_string={
            "author_party_q": "Partido Verde",
            "leg_period_q": "2021-2026",
        },
    ).get_data(as_text=True)
    assert "Bill by Naranja author" not in non_matching


def test_no_js_date_fallback_markup_present(client):
    body = client.get("/bills").get_data(as_text=True)

    assert "<noscript>" in body
    assert 'name="presentation_date_from_year"' in body
    assert 'name="presentation_date_from_month"' in body
    assert 'name="presentation_date_from_day"' in body
    assert 'name="presentation_date_to_year"' in body
    assert 'name="presentation_date_to_month"' in body
    assert 'name="presentation_date_to_day"' in body
    # The noscript-wrapped legacy grid must close before the diff panel.
    assert body.index("</noscript>") < body.index("Tiene diferencia de versiones")


def test_chamber_badge_renders_on_result_rows(client, session_factory):
    _seed_bicameral_bills(session_factory)

    body = client.get("/bills", query_string={"title_q": "Bill"}).get_data(as_text=True)

    assert "chamber-badge--senado" in body
    assert "chamber-badge--diputados" in body


def test_chamber_selector_hidden_for_legacy_period(client):
    legacy_body = client.get(
        "/bills", query_string={"leg_period_q": "2021-2026"}
    ).get_data(as_text=True)
    assert 'class="chamber-tabs"' not in legacy_body

    modern_body = client.get(
        "/bills", query_string={"leg_period_q": "2026-2031"}
    ).get_data(as_text=True)
    assert 'class="chamber-tabs"' in modern_body


def test_chamber_column_hidden_for_legacy_period(client, session_factory):
    _seed_bicameral_bills(session_factory)

    legacy_body = client.get(
        "/bills", query_string={"leg_period_q": "2021-2026"}
    ).get_data(as_text=True)
    assert "Cámara" not in legacy_body

    modern_body = client.get(
        "/bills", query_string={"title_q": "Bill", "leg_period_q": "2026-2031"}
    ).get_data(as_text=True)
    assert "Cámara" in modern_body


def test_main_search_form_submits_via_post_with_no_query_string(
    client, session_factory
):
    """The core ask: filters must not appear in the URL. The search form
    itself posts to a bare /bills action -- no query string involved at
    all, with or without JS."""
    _seed_bill_search_data(session_factory)

    response = client.post(
        "/bills", data={"title_q": "Bill 0001", "leg_period_q": "2021-2026"}
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'method="post"' in body
    assert "2021_0001" in body
    assert "2021_0002" not in body


def test_period_tab_is_a_post_form_not_a_link(client, session_factory):
    """Tabs/pagination must never be plain <a href="?..."> GET links --
    they're POST forms with hidden inputs replicating the active filters,
    so clicking one never puts anything in the address bar."""
    _seed_bicameral_bills(session_factory)

    body = client.get(
        "/bills", query_string={"title_q": "Bill", "leg_period_q": "2026-2031"}
    ).get_data(as_text=True)

    assert 'href="/bills?' not in body
    assert '<form method="post" action="/bills"' in body
    assert '<input type="hidden" name="title_q" value="Bill">' in body

    # Simulate actually clicking the "2021-2026" tab: submit its exact
    # hidden-input set.
    switched = client.post(
        "/bills", data={"title_q": "Bill", "leg_period_q": "2021-2026"}
    ).get_data(as_text=True)
    assert "Legacy Bill" in switched
    assert "Senado Bill" not in switched
