from __future__ import annotations

# Mirrors data/raw/billtext.sqlite3-query: uppercase-only search on both
# accented and unaccented heading forms; body cut before the earliest trailing
# marker; slice returned from the original raw text.

_HEADINGS = (
    # ── Two-line exact forms (original) ──────────────────────────────────────
    """EL CONGRESO DE LA REPÚBLICA
HA DADO LA LEY SIGUIENTE""",
    """EL CONGRESO DE LA REPÚBLICA
HA DADO LA LEY SIGUIENTE:""",
    """EL CONGRESO DE LA REPÚBLICA
HA DADO LA SIGUIENTE LEY""",
    """EL CONGRESO DE LA REPÚBLICA,
HA DADO LA SIGUIENTE LEY:""",
    """EL CONGRESO DE LA REPÚBLICA;
HA DADO LA LEY SIGUIENTE:""",
    """EL CONGRESO DE LA REPÚBLICA;
HA DADO LA RESOLUCIÓN LEGISLATIVA DEL CONGRESO
SIGUIENTE:""",
    """EL CONGRESO DE LA REPÚBLICA;
HA DADO LA RESOLUCIÓN LEGISLATIVA DEL CONGRESO
SIGUIENTE""",
    "FÓRMULA LEGAL",
    "FORMULA LEGAL",
    "PROYECTO DE RESOLUCION LEGISLATIVA",
    "PROYECTO DE RESOLUCIÓN LEGISLATIVA",
    """EL CONGRESO DE LA REPÚBLICA,
HA DADO LA LEY SIGUIENTE:""",
    """EL CONGRESO DE LA REPÚBLICA
HA DADO LA LEY SIGUIENTE: """,
    """EL CONGRESO DE LA REPÚBLICА;
HA DADO LA LEY SIGUIENTE:""",
    # ── Standalone second-line anchors (high-priority) ───────────────────────
    # El Peruano two-column OCR inserts phone numbers / codes between the two
    # heading lines, so the combined form never matches. The second line alone
    # is reliable enough to anchor the body start.
    "HA DADO LA LEY SIGUIENTE:",
    "HA DADO LA LEY SIGUIENTE: ",
    "HA DADO LA SIGUIENTE LEY:",
    "HA DADO LA SIGUIENTE LEY: ",
    "HA DADO LA RESOLUCIÓN LEGISLATIVA SIGUIENTE:",
    "HA DADO LA RESOLUCIÓN LEGISLATIVA DEL CONGRESO SIGUIENTE:",
    # ── Committee substitute / consensus texts (medium-priority) ─────────────
    "TEXTO SUSTITUTORIO",
    "TEXTO SUSTITUTORIO:",
    "TEXTO CONSENSUADO",
    "TEXTO CONSENSUADO:",
    # ── OCR-mangled variants (low-priority) ───────────────────────────────────
    "A DADO LA LEY SIGUIENTE:",  # leading H dropped by OCR
    "HA DADO LA LY SIGUENTE:",  # vowel dropout
    "HA DADO LA SIGUIENTE LEY DE REFORMA CONSTITUCIONAL",
)

_END_MARKERS = (
    "COMUNIQUESE AL SEÑOR PRESIDENTE DE LA REPUBLICA PARA SU PROMULGACIÓN",
    "COMUNÍQUESE AL SEÑOR PRESIDENTE DE LA REPÚBLICA PARA SU PROMULGACIÓN.",
    "LIMA DD DE MMMM YYYY (*) EXPOSICIÓN DE MOTIVOS",
    """COMUNÍQUESE AL SEÑOR PRESIDENTE DE LA REPÚBLICA
PARA SU PROMULGACIÓN.""",
    "COMUNIQUESE AL SEÑOR PRESIDENTE DE LA REPÚBLICA PARA SU PROMULGACIÓN.",
    """COMUNÍQUESE AL SEÑOR PRESIDENTE DE LA REPÚBLICA
PARA SU PROMULGACIÓN""",
    "COMUNÍQUESE AL SEÑOR PRESIDENTE DE LA REPÚBLICA PARA SU PROMULGACIÓN. ",
    "LIMA, DD DE MMMM DE YYYY (*) EXPOSICIÓN DE MOTIVOS",
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
