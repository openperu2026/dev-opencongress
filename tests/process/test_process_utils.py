import json
from datetime import date, datetime

from backend.process.utils import (
    find_organization_schema,
    chamber_label_from_id,
    gen_congresistas_df,
)
from backend.process.schema import BillOrganization
from backend.database.raw_models import RawBill, RawMotion


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


def _bill(id_, firmantes, *, last_update=True):
    return RawBill(
        id=id_,
        congresistas=json.dumps(firmantes),
        timestamp=datetime(2026, 1, 1),
        last_update=last_update,
    )


def _motion(id_, firmantes, *, last_update=True):
    return RawMotion(
        id=id_,
        congresistas=json.dumps(firmantes),
        timestamp=datetime(2026, 1, 1),
        last_update=last_update,
    )


_LEGACY_FIRMANTE = {
    "firmanteId": 1,
    "tipoFirmanteId": 1,
    "congresistaId": 4,
    "nombre": "Aguinaga Recuenco, Alejandro Aurelio",
    "dni": "08236035",
    "sexo": "M",
    "pagWeb": "https://www.congreso.gob.pe/congresistas2021/AlejandroAguinaga/",
}

_CHAMBER_BILL_FIRMANTE = {
    "firmanteId": 2,
    "tipoFirmanteId": 1,
    "congresistaId": 182,
    "nombre": "Gamarra Pita, Luzmila María del Carmen",
    "dni": "42516751",
    "sexo": "F",
    "pagWeb": None,
}

_CHAMBER_MOTION_FIRMANTE_NO_DNI = {
    "firmanteId": 3,
    "tipoFirmanteId": 1,
    "congresistaId": 292,
    "nombre": "Miyashiro Arashiro, Marco Enrique",
    "pagWeb": None,
    "sexo": "M",
    "desGpar": "Fuerza Popular",
}


def test_gen_congresistas_df_default_unchanged_by_new_format_rows(session):
    """Regression: leg_period=None (default) must be byte-identical to
    before the id-format filter was added -- includes every row regardless
    of format, still requires "dni"."""
    session.add(_bill("2021_100", [_LEGACY_FIRMANTE]))
    session.add(_bill("00006-2026-2031-S", [_CHAMBER_BILL_FIRMANTE]))
    session.add(_motion("00054-2026-2031-S", [_CHAMBER_MOTION_FIRMANTE_NO_DNI]))
    session.commit()

    df = gen_congresistas_df(session)

    ids = set(df["congresistaId"].to_list())
    # Legacy row (has dni) and the chamber BILL row (has dni) both survive;
    # the chamber MOTION row (no dni) is excluded, same "dni required"
    # filter as always -- leg_period=None does not relax it.
    assert ids == {4, 182}


def test_gen_congresistas_df_2026_2031_filters_to_new_format_ids_only(session):
    session.add(_bill("2021_100", [_LEGACY_FIRMANTE]))
    session.add(_bill("00006-2026-2031-S", [_CHAMBER_BILL_FIRMANTE]))
    session.add(_motion("00054-2026-2031-S", [_CHAMBER_MOTION_FIRMANTE_NO_DNI]))
    session.commit()

    df = gen_congresistas_df(session, leg_period="2026-2031")

    ids = set(df["congresistaId"].to_list())
    # Legacy row excluded entirely; both chamber rows included even though
    # the motion firmante has no "dni" -- relaxed filter for this period.
    assert ids == {182, 292}


def test_gen_congresistas_df_2026_2031_saves_to_distinct_filename(session, monkeypatch):
    saved = {}
    session.add(_bill("00006-2026-2031-S", [_CHAMBER_BILL_FIRMANTE]))
    session.commit()

    class _FakeWritable:
        def write_json(self, path):
            saved["path"] = path

    import backend.process.utils as utils_mod

    monkeypatch.setattr(
        utils_mod.pl,
        "DataFrame",
        lambda data: _FakeWritable(),
    )

    gen_congresistas_df(session, save=True, leg_period="2026-2031")

    assert saved["path"].name == "cong_info_2026_2031.json"
