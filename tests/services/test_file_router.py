from app.services.file_router import route_and_parse_file
def test_route_and_parse_file():
    txt = route_and_parse_file("data.json", b'{"a": 1}')
    assert "{'a': 1}" in txt
