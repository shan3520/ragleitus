from app.services.csv_extraction import parse_csv_content
def test_parse_csv_content():
    rows = parse_csv_content("name,age\nAlice,30")
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice"
