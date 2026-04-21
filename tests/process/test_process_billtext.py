from backend.process.billtext import extract_bill_body, normalize_bill_text


def test_normalize_preserves_accents():
    assert normalize_bill_text("próyecto") == "PRÓYECTO"


def test_extract_starts_at_first_anchor():
    raw = "OFICIO blah blah PROYECTO DE LEY Nº 1\nARTICULO 1..."
    out = extract_bill_body(raw)
    assert out is not None
    assert out.startswith("PROYECTO DE LEY")


def test_extract_preserves_original_casing_and_accents():
    raw = "oficio previo... Exposición de Motivos: el presente proyecto..."
    out = extract_bill_body(raw)
    assert out is not None
    assert out.startswith("Exposición de Motivos")


def test_extract_trims_trailing_marker():
    raw = (
        "cover page\n"
        "PROYECTO DE LEY Nº 1\n"
        "cuerpo del proyecto aquí.\n"
        "CONSEJO DIRECTIVO DEL CONGRESO acuerda..."
    )
    out = extract_bill_body(raw)
    assert out is not None
    assert out.startswith("PROYECTO DE LEY")
    assert "CONSEJO DIRECTIVO DEL CONGRESO" not in out
    assert out.rstrip().endswith("cuerpo del proyecto aquí.")


def test_extract_returns_none_without_anchor():
    assert extract_bill_body("solo oficio sin marcadores") is None
