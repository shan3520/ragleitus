from app.core.sanitization import sanitize_string

def test_sanitize_string():
    assert sanitize_string("Clean text\t") == "Clean text"
    assert sanitize_string("") == ""
