from datetime import date

import pytest

from backend import LegPeriod, RoleOrganization, TypeOrganization
from backend.database import models as db_models
from backend.database.crud import pipeline_core as crud_core
from backend.process import schema


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


def test_upsert_bancada_uses_organization_rows(session):
    existing = crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Accion Popular",
            org_type=TypeOrganization.BANCADA,
        ),
    )

    same = crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Accion Popular",
            org_type="Bancada",
        ),
    )
    inserted = crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Fuerza Popular",
            org_type=TypeOrganization.BANCADA,
        ),
    )

    assert same.org_id == existing.org_id
    assert inserted.org_id != existing.org_id
    assert session.query(db_models.Organization).count() == 2


def test_upsert_bancada_membership_is_idempotent(session, create_congresista):
    congresista = create_congresista()
    bancada = crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Accion Popular",
            org_type=TypeOrganization.BANCADA,
        ),
    )

    first = crud_core.upsert_membership(
        session,
        person_id=congresista.id,
        org_id=bancada.org_id,
        leg_period=LegPeriod.PERIODO_2021_2026,
        org_type=TypeOrganization.BANCADA,
        role=RoleOrganization.MIEMBRO,
        start_date=date(2025, 7, 28),
        end_date=date(2026, 7, 28),
    )
    second = crud_core.upsert_membership(
        session,
        person_id=congresista.id,
        org_id=bancada.org_id,
        leg_period="2021-2026",
        org_type="Bancada",
        role="Miembro",
        start_date=date(2025, 7, 28),
        end_date=date(2026, 7, 28),
    )

    assert second.id == first.id
    assert session.query(db_models.BancadaMembership).count() == 1
    assert session.query(db_models.Membership).count() == 1


def test_upsert_organization_same_name_type_different_parent_creates_two_rows(
    session,
):
    """CRITICAL regression: this is the exact bug the bicameral migration's
    Step 4b fix exists for. Before the fix, upserting the second chamber's
    same-named committee would match the first chamber's row via
    find_organization (name+type only) and silently overwrite its
    parent_org_id, corrupting every membership that pointed at it."""
    diputados = crud_core.upsert_organization(
        session,
        schema.Organization(org_name="Cámara de Diputados", org_type="Cámara"),
    )
    senado = crud_core.upsert_organization(
        session,
        schema.Organization(org_name="Senado de la República", org_type="Cámara"),
    )

    committee_diputados = crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Comisión de Justicia",
            org_type="Comisión",
            parent_org_name="Cámara de Diputados",
            parent_org_type="Cámara",
        ),
    )
    committee_senado = crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Comisión de Justicia",
            org_type="Comisión",
            parent_org_name="Senado de la República",
            parent_org_type="Cámara",
        ),
    )

    assert committee_diputados.org_id != committee_senado.org_id
    assert committee_diputados.parent_org_id == diputados.org_id
    assert committee_senado.parent_org_id == senado.org_id
    assert (
        session.query(db_models.Organization)
        .filter(db_models.Organization.org_name == "Comisión de Justicia")
        .count()
        == 2
    )


def test_upsert_organization_same_name_type_same_parent_updates_in_place(session):
    crud_core.upsert_organization(
        session,
        schema.Organization(org_name="Cámara de Diputados", org_type="Cámara"),
    )

    first = crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Comisión de Economía",
            org_type="Comisión",
            parent_org_name="Cámara de Diputados",
            parent_org_type="Cámara",
        ),
    )
    second = crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Comisión de Economía",
            org_type="Comisión",
            org_link="updated-link",
            parent_org_name="Cámara de Diputados",
            parent_org_type="Cámara",
        ),
    )

    assert second.org_id == first.org_id
    assert second.org_link == "updated-link"
    assert (
        session.query(db_models.Organization)
        .filter(db_models.Organization.org_name == "Comisión de Economía")
        .count()
        == 1
    )


def test_upsert_organization_with_no_parent_unaffected_by_parent_scoping(session):
    """Chambers and parties are top-level (parent_org_id=NULL) -- confirms the
    parent_org_id fix doesn't regress orgs that never had a parent to begin
    with."""
    first = crud_core.upsert_organization(
        session,
        schema.Organization(org_name="Partido Morado", org_type="Partido"),
    )
    second = crud_core.upsert_organization(
        session,
        schema.Organization(org_name="Partido Morado", org_type="Partido"),
    )

    assert second.org_id == first.org_id
    assert first.parent_org_id is None
    assert (
        session.query(db_models.Organization)
        .filter(db_models.Organization.org_name == "Partido Morado")
        .count()
        == 1
    )


def test_find_organization_parent_org_id_scoping(session):
    diputados = crud_core.upsert_organization(
        session,
        schema.Organization(org_name="Cámara de Diputados", org_type="Cámara"),
    )
    senado = crud_core.upsert_organization(
        session,
        schema.Organization(org_name="Senado de la República", org_type="Cámara"),
    )
    committee_diputados = crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Comisión de Salud",
            org_type="Comisión",
            parent_org_name="Cámara de Diputados",
            parent_org_type="Cámara",
        ),
    )
    crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Comisión de Salud",
            org_type="Comisión",
            parent_org_name="Senado de la República",
            parent_org_type="Cámara",
        ),
    )

    # Scoped by the Diputados parent finds only the Diputados committee.
    found = crud_core.find_organization(
        session,
        org_name="Comisión de Salud",
        org_type="Comisión",
        parent_org_id=diputados.org_id,
    )
    assert found.org_id == committee_diputados.org_id

    # Unscoped (parent_org_id omitted) preserves prior behavior: picks by
    # fuzzy score then lowest org_id -- still returns *a* match, not an error.
    unscoped = crud_core.find_organization(
        session, org_name="Comisión de Salud", org_type="Comisión"
    )
    assert unscoped is not None

    # A parent_org_id that doesn't match either committee finds nothing.
    none_found = crud_core.find_organization(
        session,
        org_name="Comisión de Salud",
        org_type="Comisión",
        parent_org_id=senado.org_id + 999,
    )
    assert none_found is None


def test_membership_exists(session, create_congresista):
    cong = create_congresista()
    org = crud_core.upsert_organization(
        session,
        schema.Organization(
            org_name="Fuerza Popular", org_type=TypeOrganization.BANCADA
        ),
    )

    # Nothing recorded yet.
    assert (
        crud_core.membership_exists(
            session,
            person_id=cong.id,
            org_id=org.org_id,
            leg_period="2026-2031",
            org_type=TypeOrganization.BANCADA,
        )
        is False
    )

    crud_core.upsert_membership(
        session,
        person_id=cong.id,
        org_id=org.org_id,
        leg_period="2026-2031",
        org_type=TypeOrganization.BANCADA,
        role=RoleOrganization.MIEMBRO,
        start_date=date(2026, 7, 28),
        end_date=date(2027, 7, 28),
    )

    # Now exists -- and the check is independent of role/dates (unlike
    # upsert_membership's own exact-match existing-row lookup).
    assert (
        crud_core.membership_exists(
            session,
            person_id=cong.id,
            org_id=org.org_id,
            leg_period="2026-2031",
            org_type=TypeOrganization.BANCADA,
        )
        is True
    )

    # A different leg_period/org_type for the same person+org is unaffected.
    assert (
        crud_core.membership_exists(
            session,
            person_id=cong.id,
            org_id=org.org_id,
            leg_period="2021-2026",
            org_type=TypeOrganization.BANCADA,
        )
        is False
    )
