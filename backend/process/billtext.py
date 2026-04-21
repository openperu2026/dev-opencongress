from __future__ import annotations

# Mirrors data/raw/billtext.sqlite3-query: uppercase-only search on both
# accented and unaccented heading forms; body cut before the earliest trailing
# marker; slice returned from the original raw text.

_HEADINGS = (
    "PROYECTO DE LEY",
    "PROYECTO DE RESOLUCION LEGISLATIVA",
    "PROYECTO DE RESOLUCIÓN LEGISLATIVA",
    "EXPOSICION DE MOTIVOS",
    "EXPOSICIÓN DE MOTIVOS",
    "FORMULA LEGAL",
    "FÓRMULA LEGAL",
    "ARTICULO 1",
    "ARTÍCULO 1",
    "ARTICULO PRIMERO",
    "ARTÍCULO PRIMERO",
)

_END_MARKERS = (
    "CONSEJO DIRECTIVO DEL CONGRESO",
    "EN SESION DE LA FECHA, TOMO CONOCIMIENTO DEL DICTAMEN",
    "EN SESIÓN DE LA FECHA, TOMÓ CONOCIMIENTO DEL DICTAMEN",
)


def normalize_bill_text(s: str) -> str:
    """Uppercase-only search form; accents preserved so indices match ``raw_text``."""
    return s.upper()


def _earliest_match(
    haystack: str, needles: tuple[str, ...], min_pos: int = 0
) -> int | None:
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
