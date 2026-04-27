from __future__ import annotations

# Mirrors data/raw/billtext.sqlite3-query: uppercase-only search on both
# accented and unaccented heading forms; body cut before the earliest trailing
# marker; slice returned from the original raw text.

_HEADINGS = (
    """EL CONGRESO DE LA REPÚBLICA
HA DADO LA LEY SIGUIENTE""",
    """EL CONGRESO DE LA REPÚBLICA
Ha dado la Ley siguiente:""",
    """El Congreso de la República
Ha dado la siguiente Ley"""
    """El Congreso de la República,
Ha dado la siguiente Ley:""",
    """EL CONGRESO DE LA REPÚBLICA;
Ha dado la Ley siguiente:""",
    """El Congreso de la República;
Ha dado la Ley siguiente:""",
    """EL CONGRESO DE LA REPÚBLICA;
Ha dado la Resolución Legislativa del Congreso
siguiente:""",
    """EL CONGRESO DE LA REPÚBLICA;
Ha dado la Resolución Legislativa del Congreso
siguiente""",
    """FÓRMULA LEGAL""",
    "PROYECTO DE RESOLUCION LEGISLATIVA",
    "PROYECTO DE RESOLUCIÓN LEGISLATIVA",
    "FORMULA LEGAL",
    "FÓRMULA LEGAL",
    """EL CONGRESO DE LA REPÚBLICA,
Ha dado la Ley siguiente:""",
    """El Congreso de la República
Ha dado la Ley siguiente: """,
    """EL CONGRESO DE LA REPÚBLICА;
Ha dado la Ley siguiente:""",
)

_END_MARKERS = (
    "COMUNIQUESE AL SEÑOR PRESIDENTE DE LA REPUBLICA PARA SU PROMULGACIÓN",
    "Comuníquese al señor Presidente de la República para su promulgación."
    "Lima DD de MMMM YYYY (*) EXPOSICIÓN DE MOTIVOS"
    """Comuníquese al señor Presidente de la República
para su promulgación."""
    """Comuniquese al señor presidente de la República para su promulgación.""",
    """Comuníquese al señor Presidente de la República
para su promulgación""",
    """Comuníquese al señor Presidente de la República para su promulgación. """,
    """Lima, DD de MMMM de YYYY (*) EXPOSICIÓN DE MOTIVOS""",
)


def normalize_bill_text(s: str) -> str:
    """Uppercase-only search form; accents preserved so indices match ``raw_text``."""
    return s.upper()


def _earliest_match(
    haystack: str, needles: tuple[str, ...], min_pos: int = 0
) -> int | None:
    """This function searches for needles in a haystack. In other words, we search for a START or END sequence in a bill."""
    hits = [i for i in (haystack.find(n) for n in needles) if i >= min_pos]
    return min(hits) if hits else None


def extract_bill_body(raw_text: str) -> str | None:
    """Return the raw-text slice from the first heading, trimmed before any end marker."""
    if not (raw_text or "").strip():
        return None
    norm = normalize_bill_text(raw_text)
    start = _earliest_match(norm, _HEADINGS)
    if start is None:
        return None
    # min_pos=1: SQL guards end_rel > 1 so a marker at the very start is ignored.
    end_rel = _earliest_match(norm[start:], _END_MARKERS, min_pos=1)
    if end_rel is None:
        return raw_text[start:]
    return raw_text[start : start + end_rel]
