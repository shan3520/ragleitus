from app.services.json_extraction import parse_json_content
def test_parse_json_content():
    data = parse_json_content('{"key": "value"}')
    assert data["key"] == "value"
