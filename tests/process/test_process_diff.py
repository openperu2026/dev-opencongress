from backend.process.diff import compute_bill_difference, _normalize_for_diff


def test_both_none_returns_unavailable():
    result = compute_bill_difference(None, None)
    assert result["type"] == "unavailable"
    assert result["content"] is None


def test_old_none_returns_first_version():
    result = compute_bill_difference(None, "some text")
    assert result["type"] == "first_version"
    assert result["content"] is None


def test_equal_texts_returns_no_change():
    text = "line one\nline two\n"
    result = compute_bill_difference(text, text)
    assert result["type"] == "no_change"
    assert result["content"] is None


def test_different_texts_returns_modified():
    old = "line one\nline two\n"
    new = "line one\nline three\n"
    result = compute_bill_difference(old, new)
    assert result["type"] == "modified"
    assert isinstance(result["content"], list)
    assert any(line.startswith("- ") for line in result["content"])
    assert any(line.startswith("+ ") for line in result["content"])


def test_new_none_treated_as_removal():
    old = "line one\nline two\n"
    result = compute_bill_difference(old, None)
    assert result["type"] == "modified"
    assert all(
        line.startswith("- ") or line.startswith("? ")
        for line in result["content"]
        if line.strip()
    )


# ── Fix 3: size-ratio guard ──────────────────────────────────────────────────


def test_large_size_ratio_returns_incomparable():
    old = "x " * 5000  # ~10 000 chars
    new = "y"  # 1 char — ratio >> 10
    result = compute_bill_difference(old, new)
    assert result["type"] == "incomparable"
    assert result["content"] is None


def test_ratio_just_under_threshold_is_modified():
    new = "word " * 10  # 50 chars — ratio = 10, just at boundary
    # At exactly 10× we expect incomparable; anything < 10 should be modified
    small_old = "word " * 99  # 495 chars — ratio ~9.9
    result = compute_bill_difference(small_old, new)
    assert result["type"] in ("modified", "no_change")


# ── Fix 2: normalization ─────────────────────────────────────────────────────


def test_normalize_collapses_single_newlines():
    text = "first line\nsecond line\nthird line"
    norm = _normalize_for_diff(text)
    assert "\n" not in norm  # all joined into one line
    assert "first line" in norm
    assert "third line" in norm


def test_normalize_preserves_paragraph_breaks():
    text = "paragraph one\n\nparagraph two"
    norm = _normalize_for_diff(text)
    assert "\n\n" in norm or norm.count("\n") >= 1


def test_reflow_noise_produces_no_change():
    # Same sentence, different OCR line-breaks — should normalize to no_change
    old = "Artículo 1. Se aprueba el presupuesto\npor el monto de S/ 1 000 000,00\npara el año fiscal 2023."
    new = "Artículo 1. Se aprueba el presupuesto por el monto de\nS/ 1 000 000,00 para el año fiscal 2023."
    result = compute_bill_difference(old, new)
    assert result["type"] == "no_change"


def test_real_change_still_detected_after_normalization():
    old = "Artículo 1. El monto es S/ 1 000 000,00\npara el año 2023."
    new = "Artículo 1. El monto es S/ 2 000 000,00\npara el año 2023."
    result = compute_bill_difference(old, new)
    assert result["type"] == "modified"
    assert any(
        "1 000 000" in line for line in result["content"] if line.startswith("- ")
    )
    assert any(
        "2 000 000" in line for line in result["content"] if line.startswith("+ ")
    )
