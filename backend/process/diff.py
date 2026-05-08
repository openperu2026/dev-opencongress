import difflib
import re

# Documents whose sizes differ by more than this factor are flagged as
# incomparable rather than producing a noisy diff (e.g. full dictamen vs
# a short amendment letter).
_MAX_SIZE_RATIO = 10.0


def _normalize_for_diff(text: str) -> str:
    """
    Collapse OCR line-reflow noise before diffing.

    Single newlines (mid-sentence OCR breaks) are joined into the surrounding
    line.  Double newlines (genuine paragraph breaks) and leading/trailing
    whitespace per line are preserved.
    """
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def compute_bill_difference(old_text: str | None, new_text: str | None) -> dict:
    """
    Compare two versions of bill body text.

    Returns a dict with:
      - type: "modified" | "first_version" | "no_change" |
              "unavailable" | "incomparable"
      - content: list of ndiff lines (str), or None

    "incomparable" is returned when the two texts differ in length by more
    than _MAX_SIZE_RATIO, indicating mismatched document types rather than a
    genuine revision.
    """
    if old_text is None and new_text is None:
        return {"type": "unavailable", "content": None}
    if old_text is None:
        return {"type": "first_version", "content": None}

    # Fix 3: size-ratio guard
    if new_text:
        lo, hi = sorted([len(old_text), len(new_text)])
        if lo > 0 and hi / lo > _MAX_SIZE_RATIO:
            return {"type": "incomparable", "content": None}

    if old_text == new_text:
        return {"type": "no_change", "content": None}

    # Fix 2: normalize before diffing to collapse OCR line-reflow noise
    old_norm = _normalize_for_diff(old_text)
    new_norm = _normalize_for_diff(new_text) if new_text else ""

    if old_norm == new_norm:
        return {"type": "no_change", "content": None}

    old_lines = old_norm.splitlines(keepends=True)
    new_lines = new_norm.splitlines(keepends=True)
    diff_lines = list(difflib.ndiff(old_lines, new_lines))
    return {"type": "modified", "content": diff_lines}
