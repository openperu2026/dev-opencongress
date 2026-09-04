from backend.config import settings
from backend.core.enums import LegPeriod


def test_settings_leg_period_defaults_to_current_term():
    """settings.LEG_PERIOD must be a properly declared field (not reliant
    on pydantic-settings' undeclared-extra-field lowercase fallback, i.e.
    NOT only reachable as settings.leg_period), defaulting to the current
    term when .env doesn't override it."""
    assert settings.LEG_PERIOD == LegPeriod.PERIODO_2026_2031.value
