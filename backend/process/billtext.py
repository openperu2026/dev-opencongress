from __future__ import annotations

_SENTINEL = 999_999_999

# Order matches SQL: nested MIN of INSTR values (earliest start wins)
_ANCHORS = (
    "PROYECTO DE LEY",
    "PROYECTO DE RESOLUCION LEGISLATIVA",
    "EXPOSICION DE MOTIVOS",
    "FORMULA LEGAL",
    "ARTICULO 1",
    "ARTICULO PRIMERO",
)


def normalize_bill_text(s: str) -> str:
    """Uppercase + accent fold (same idea as billtext.sqlite3-query)."""
    t = s
    for a, b in (
        ("á", "a"),
        ("é", "e"),
        ("í", "i"),
        ("ó", "o"),
        ("ú", "u"),
        ("Á", "A"),
        ("É", "E"),
        ("Í", "I"),
        ("Ó", "O"),
        ("Ú", "U"),
        ("ñ", "n"),
        ("Ñ", "N"),
        ("ü", "u"),
        ("Ü", "U"),
    ):
        t = t.replace(a, b)
    return t.upper()


def _first_anchor_pos(norm: str) -> int | None:
    positions: list[int] = []
    for needle in _ANCHORS:
        i = norm.find(needle)
        if i >= 0:
            positions.append(i)
    if not positions:
        return None
    return min(positions)


def extract_bill_body(raw_text: str) -> str | None:
    """
    Return substring from first anchor to end of string, in normalized space.
    SQL uses 1-based SUBSTR; Python uses 0-based slice.
    """
    if not (raw_text or "").strip():
        return None
    norm = normalize_bill_text(raw_text)
    start = _first_anchor_pos(norm)
    if start is None:
        return None
    return norm[start:]
