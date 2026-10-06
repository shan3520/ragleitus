from app.core.sanitization import sanitize_string

def test_sanitize_string():
    assert sanitize_string("Clean text\t") == "Clean text"
    assert sanitize_string("") == ""


def test_spreadsheet_safe_keeps_formulas_as_text():
    from app.core.sanitization import spreadsheet_safe

    assert spreadsheet_safe("=HYPERLINK(\"http://evil\")") == "'=HYPERLINK(\"http://evil\")"
    assert [spreadsheet_safe(v) for v in ("+1", "-1", "@SUM(A1)", "\tx")] == ["'+1", "'-1", "'@SUM(A1)", "'\tx"]
    assert spreadsheet_safe("gpt-4o-mini") == "gpt-4o-mini" and spreadsheet_safe(3) == 3 and spreadsheet_safe(None) is None
