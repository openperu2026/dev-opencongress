from datetime import date

from backend.process.utils import find_organization_schema, chamber_label_from_id
from backend.process.schema import BillOrganization


def _bill_org(org_name: str, org_type: str) -> BillOrganization:
    return BillOrganization(
        bill_id="2026_1",
        org_name=org_name,
        org_type=org_type,
        presentation_date=date(2026, 1, 1),
        decision_date=None,
    )


def test_find_organization_schema_matches_by_type_only():
    """T4: relaxed to match by org_type alone once org_name is omitted --
    needed so a bill's chamber-type entry can be found without assuming it's
    Diputados."""
    orgs = [
        _bill_org("Comisión de Justicia", "Comisión"),
        _bill_org("Senado de la República", "Cámara"),
    ]

    found = find_organization_schema(orgs, org_type="Cámara")

    assert found is not None
    assert found.org_name == "Senado de la República"


def test_find_organization_schema_still_matches_by_name_when_given():
    """Regression: existing callers that pass org_name explicitly keep working."""
    orgs = [
        _bill_org("Cámara de Diputados", "Cámara"),
    ]

    found = find_organization_schema(
        orgs, org_type="Cámara", org_name="Cámara de Diputados"
    )
    not_found = find_organization_schema(
        orgs, org_type="Cámara", org_name="Senado de la República"
    )

    assert found is not None
    assert not_found is None


def test_find_organization_schema_no_match_returns_none():
    orgs = [_bill_org("Comisión de Justicia", "Comisión")]

    assert find_organization_schema(orgs, org_type="Cámara") is None


def test_chamber_label_from_id_variants():
    assert chamber_label_from_id("00006-2026-2031-S") == "Senadores"
    assert chamber_label_from_id("00102-2026-2031-CD") == "Diputados"
    assert chamber_label_from_id("2021_14864") is None
    assert chamber_label_from_id("PL_123") is None
