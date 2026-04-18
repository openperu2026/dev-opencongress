from backend.process.billtext import extract_bill_body, normalize_bill_text


def test_normalize_accent_fold():
    assert "PROYECTO" in normalize_bill_text("próyecto")


def test_extract_starts_at_first_anchor():
    raw = "OFICIO blah blah PROYECTO DE LEY Nº 1\nARTICULO 1..."
    out = extract_bill_body(raw)
    assert out is not None
    assert out.startswith("PROYECTO DE LEY")


def test_extract_returns_none_without_anchor():
    assert extract_bill_body("solo oficio sin marcadores") is None
