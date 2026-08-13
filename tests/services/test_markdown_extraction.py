from app.services.markdown_extraction import parse_markdown_headers
def test_parse_markdown_headers():
    secs = parse_markdown_headers("# Section 1\nText 1\n# Section 2\nText 2")
    assert len(secs) == 2
    assert secs[0]["header"] == "Section 1"
