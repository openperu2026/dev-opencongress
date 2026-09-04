from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.enums import (
    Proponents,
    RoleOrganization,
    TypeBillStep,
    TypeMotion,
    TypeMotionStep,
)
from backend.core.parsers import (
    classify_des_estado,
    classify_motion_des_estado,
    normalize_membership_role,
    get_processable_year_range,
    resolve_processable_leg_periods,
    parse_comm_type,
    parse_motion_type,
    parse_proponent,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> list[dict]:
    with path.open() as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise TypeError(f"Expected list payload in {path}")
    return payload


def test_classify_bill_status_exact():
    label = classify_des_estado("APROBADO", "ASISTENCIA Y VOTACIÓN")

    assert label is TypeBillStep.VOTACION


def test_classify_bill_status_normalizes_variant():
    label = classify_des_estado(" Aprobado Com.Permanente ", "VOTACION")

    assert label is TypeBillStep.VOTACION


def test_classify_bill_status_uses_detail_when_placeholder():
    label = classify_des_estado(
        "------",
        "TEXTO SUSTITUTORIO DE LA COMISIÓN DE SALUD",
    )

    assert label is TypeBillStep.TEXTO_SUSTITUTORIO_O_REVISION


def test_classify_bill_status_uses_detail_to_refine_dictamen():
    label = classify_des_estado(
        "DICTAMEN",
        "POR UNANIMIDAD - FÓRMULA SUSTITUTORIA - LEY QUE CREA EL COLEGIO PROFESIONAL",
    )

    assert label is TypeBillStep.TEXTO_SUSTITUTORIO_O_REVISION


def test_classify_bill_detail_vote_overrides_debate_status():
    label = classify_des_estado(
        "EN DEBATE - PLENO",
        "ASISTENCIA Y VOTACIÓN - RECONSIDERACIÓN (APROBADA)",
    )

    assert label is TypeBillStep.VOTACION


def test_classify_bill_title_reconsideracion_does_not_force_step_type():
    label = classify_des_estado(
        "PRESENTADO",
        "LEY QUE REDUCE LOS PLAZOS PARA LA PRESENTACIÓN DE RECURSOS IMPUGNATIVOS DE RECONSIDERACIÓN",
    )

    assert label is TypeBillStep.PRESENTADO


def test_classify_motion_status_maps_foundation():
    label = classify_motion_des_estado(
        "Fundamentada la Moción",
        "LA CONGRESISTA FUNDAMENTA LA MOCIÓN DE ORDEN DEL DÍA.",
    )

    assert label is TypeMotionStep.FUNDAMENTACION


def test_classify_motion_status_uses_detail_for_blank_status():
    label = classify_motion_des_estado(
        "",
        "La Presidenta anunció que se había presentado la moción de censura.",
    )

    assert label is TypeMotionStep.ANUNCIO_O_DACION_DE_CUENTA


def test_classify_motion_status_maps_withdrawn_case():
    label = classify_motion_des_estado(
        "Se deje sin efecto",
        "Solicita que ya no sea debatida en la sesión del pleno.",
    )

    assert label is TypeMotionStep.RETIRADO


def test_classify_motion_blank_title_as_presented():
    label = classify_motion_des_estado(
        "",
        "Censurar a la señora María del Carmen Alva Prieto por su conducta antidemocrática.",
    )

    assert label is TypeMotionStep.PRESENTADO


def test_classify_motion_blank_document_as_official_communication():
    label = classify_motion_des_estado(
        "",
        "ACTA DE ACUERDO DE LA COMISIÓN DE SALUD",
    )

    assert label is TypeMotionStep.COMUNICACION_OFICIAL


def test_classify_motion_detail_title_overrides_routing_status():
    label = classify_motion_des_estado(
        "PARA SER VISTA POR EL CONSEJO DIRECTIVO",
        "Expresar su más cálido saludo y felicitación a los ciudadanos del distrito",
    )

    assert label is TypeMotionStep.PRESENTADO


def test_classify_motion_detail_document_overrides_routing_status():
    label = classify_motion_des_estado(
        "TRAMITADA CON ACUERDO DE CD",
        "OFICIO 0021-2021-2022-ADP-M-CR. LA PRIMERA VICEPRESIDENTA COMUNICA A LA DIRECTORA",
    )

    assert label is TypeMotionStep.COMUNICACION_OFICIAL


def test_classify_motion_vote_detail_keeps_vote_family():
    label = classify_motion_des_estado(
        "Aprobada",
        "APROBADO UN TEXTO SUSTITUTORIO",
    )

    assert label is TypeMotionStep.VOTACION_O_DECISION


@pytest.mark.parametrize(
    "raw_value, expected",
    [
        ("MOCIÓN DE SALUDO", TypeMotion.SALUDO),
        ("PEDIDO DE CONFORMACIÓN DE COMISIÓN ESPECIAL", TypeMotion.COMISION_ESPECIAL),
        (
            "Pedido de invitación al Consejo de Ministros o a los ministros "
            "en forma individual para informar",
            TypeMotion.INFORME_MINISTROS,
        ),
        ("DE INTERÉS NACIONAL", TypeMotion.INTERES),
    ],
)
def test_parse_motion_type_recognizes_2026_2031_senado_labels(raw_value, expected):
    """Regression test: these 4 real Senado desTipoMocion labels were missing
    from MOTION_TYPE_ALIASES, causing every single 2026-2031 Senado motion
    (64/64 at the time this was found) to fail process_motion() with an
    unhandled Pydantic ValidationError."""
    assert parse_motion_type(raw_value) is expected


def test_parse_motion_type_still_recognizes_legacy_exact_enum_values():
    assert parse_motion_type("Saludo") is TypeMotion.SALUDO
    assert parse_motion_type("Interés Nacional") is TypeMotion.INTERES


def test_parse_motion_type_raises_on_null():
    with pytest.raises(ValueError, match="cannot be null"):
        parse_motion_type(None)


def test_parse_motion_type_raises_on_unrecognized_value():
    with pytest.raises(ValueError, match="Unknown motion_type"):
        parse_motion_type("Not a real motion type")


def test_parse_proponent_recognizes_2026_2031_chamber_self_proposed_labels():
    """Regression test: the bicameral term labels a chamber-self-proposed bill
    per-chamber ("Senado de la República" / "Cámara de Diputados") instead
    of the old unicameral "Congreso" bucket -- kept as distinct Proponents
    values (not aliased to CONGRESO), so which chamber self-proposed a bill
    stays visible in bicameral-era data."""
    assert parse_proponent("Senado de la República") is Proponents.SENADO
    assert parse_proponent("Cámara de Diputados") is Proponents.DIPUTADOS


def test_parse_proponent_recognizes_executive_branch_variants():
    """Regression test: 'PODER EJECUTIVO' (uppercase) is a pre-existing gap
    affecting legacy bills, not just bicameral-era data; 'Presidente de la
    República' is a new 2026-2031 Diputados label for the same executive
    branch."""
    assert parse_proponent("PODER EJECUTIVO") is Proponents.PODER_EJECUTIVO
    assert parse_proponent("Presidente de la República") is Proponents.PODER_EJECUTIVO


def test_parse_proponent_still_recognizes_legacy_exact_and_suffixed_values():
    assert parse_proponent("Congreso") is Proponents.CONGRESO
    assert parse_proponent("Congreso-Actualización") is Proponents.CONGRESO
    assert parse_proponent("Poder Ejecutivo") is Proponents.PODER_EJECUTIVO


def test_parse_proponent_raises_on_null():
    with pytest.raises(ValueError, match="cannot be null"):
        parse_proponent(None)


def test_parse_proponent_raises_on_unrecognized_value():
    with pytest.raises(ValueError, match="Unknown proponent"):
        parse_proponent("Otros Poderes del Estado")


def test_normalize_membership_role_maps_presidency_encargado_variant():
    role = normalize_membership_role(
        "primer vicepresidente encargado de la presidencia del congreso de la república"
    )

    assert role is RoleOrganization.VICEPRESIDENTE


def test_get_processable_year_range_is_curated_not_all_history():
    """CRITICAL (found in CEO review): naively taking min/max across all of
    LEG_PERIOD_RANGES (8 entries back to 1995) would derive range(1995, 2032),
    not the intended range(2016, 2032) scoped to PROCESSABLE_LEG_PERIODS. A
    too-wide window would pass any test that only checks inclusion of
    2016-2031 -- this explicitly asserts the lower bound too."""
    result = get_processable_year_range()

    assert result == range(2016, 2032)
    assert 2015 not in result
    assert 1995 not in result
    assert 2016 in result
    assert 2031 in result


def test_get_processable_year_range_scoped_to_single_period():
    result = get_processable_year_range("2026-2031")

    assert result == range(2026, 2032)


def test_resolve_processable_leg_periods_default_returns_full_curated_list():
    result = resolve_processable_leg_periods()

    assert result == [
        "Parlamentario 2021 - 2026",
        "Parlamentario 2016 - 2021",
        "Parlamentario 2026 - 2031",
    ]


def test_resolve_processable_leg_periods_filters_to_single_period():
    result = resolve_processable_leg_periods("2026-2031")

    assert result == ["Parlamentario 2026 - 2031"]


def test_parse_comm_type_classifies_legislativa_both_chambers():
    """2026-2031 committees index section titles -- confirmed live
    2026-09-02, both chambers."""
    assert (
        parse_comm_type("Comisiones Ordinarias Legislativas")
        == "Comisión Ordinaria Legislativa"
    )


def test_parse_comm_type_classifies_no_legislativa_with_art45_suffix():
    """Diputados' section title has a trailing "(art.45)" annotation --
    must not need to match to end-of-string."""
    assert (
        parse_comm_type("Comisiones Ordinarias No Legislativas (art.45)")
        == "Comisión Ordinaria No Legislativa"
    )


def test_parse_comm_type_classifies_no_legislativa_without_art45_suffix():
    """Senado's section title omits the "(art.45)" suffix entirely."""
    assert (
        parse_comm_type("Comisiones Ordinarias No Legislativas")
        == "Comisión Ordinaria No Legislativa"
    )


def test_parse_comm_type_legacy_singular_form_unaffected():
    assert parse_comm_type("Comisión Ordinaria") == "Comisión Ordinaria"


def test_parse_comm_type_unknown_future_type_raises():
    with pytest.raises(ValueError):
        parse_comm_type("Comisiones Extraordinarias")


def test_parse_comm_type_classifies_bicameral():
    assert (
        parse_comm_type(
            "Comisión Bicameral de Presupuesto y Cuenta General de la República"
        )
        == "Comisión Bicameral"
    )
