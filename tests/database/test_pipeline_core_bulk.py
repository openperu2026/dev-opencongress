import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import LegislativeYear
from backend.database import models as db_models
from backend.database.crud import pipeline_core as crud_core


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    db_models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        yield db


@pytest.fixture()
def create_congresista(session):
    def _create_congresista(
        full_name: str = "María Grimaneza Acuña Peralta",
        first_name: str = "María Grimaneza",
        last_name: str = "Acuña Peralta",
        dni: str = "12345678",
        gender: str = "F",
        photo_url: str = "www.congreso.gob.pe/photo1",
        website: str = "https://www.congreso.gob.pe/congresistas2021/GrimanezaAcuna/",
    ) -> db_models.Congresista:
        cong = db_models.Congresista(
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            dni=dni,
            gender=gender,
            photo_url=photo_url,
            website=website,
        )
        session.add(cong)
        session.flush()
        return cong

    return _create_congresista


def test_upsert_bancadas_bulk_inserts_missing_and_reuses_existing(session):
    session.add(
        db_models.Bancada(
            leg_year=LegislativeYear.YEAR_2025_2026,
            bancada_name="Accion Popular",
        )
    )
    session.flush()

    index, inserted_count, existing_count = crud_core.upsert_bancadas_bulk(
        session,
        [
            ("2025", "ACCION POPULAR"),
            ("2025", "Fuerza Popular"),
            ("2025", "Fuerza Popular"),
        ],
    )

    assert inserted_count == 1
    assert existing_count == 1
    assert ("2025", "accion popular") in index
    assert ("2025", "fuerza popular") in index

    _, inserted_count_2, existing_count_2 = crud_core.upsert_bancadas_bulk(
        session,
        [("2025", "Accion Popular"), ("2025", "Fuerza Popular")],
    )
    assert inserted_count_2 == 0
    assert existing_count_2 == 2


def test_upsert_bancada_memberships_bulk_is_idempotent(session, create_congresista):
    b1 = db_models.Bancada(
        leg_year=LegislativeYear.YEAR_2025_2026,
        bancada_name="Accion Popular",
    )
    b2 = db_models.Bancada(
        leg_year=LegislativeYear.YEAR_2025_2026,
        bancada_name="Fuerza Popular",
    )
    session.add_all([b1, b2])
    session.flush()

    c1 = create_congresista(
        full_name="María Grimaneza Acuña Peralta",
        first_name="María Grimaneza",
        last_name="Acuña Peralta",
        dni="12345678",
        gender="F",
        photo_url="www.congreso.gob.pe/photo1",
        website="https://www.congreso.gob.pe/congresistas2021/GrimanezaAcuna/",
    )
    c2 = create_congresista(
        full_name="Juan Alberto Perez Quispe",
        first_name="Juan Alberto",
        last_name="Perez Quispe",
        dni="23456789",
        gender="M",
        photo_url="www.congreso.gob.pe/photo2",
        website="https://www.congreso.gob.pe/congresistas2021/PerezQuispe/",
    )

    session.add(
        db_models.BancadaMembership(
            leg_year=LegislativeYear.YEAR_2025_2026,
            person_id=c1.id,
            bancada_id=b1.bancada_id,
        )
    )
    session.flush()

    inserted_count = crud_core.upsert_bancada_memberships_bulk(
        session,
        [
            ("2025", c1.id, b1.bancada_id),
            ("2025", c1.id, b1.bancada_id),
            ("2025", c2.id, b2.bancada_id),
        ],
    )
    assert inserted_count == 1
    assert session.query(db_models.BancadaMembership).count() == 2

    inserted_count_2 = crud_core.upsert_bancada_memberships_bulk(
        session,
        [("2025", c1.id, b1.bancada_id), ("2025", c2.id, b2.bancada_id)],
    )
    assert inserted_count_2 == 0
    assert session.query(db_models.BancadaMembership).count() == 2
