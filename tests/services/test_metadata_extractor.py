from app.services.metadata_extractor import extract_metadata
def test_extract_metadata():
    m = extract_metadata("Doc 1", "def foo(): pass")
    assert m["title"] == "Doc 1"
    assert m["has_code"] is True
