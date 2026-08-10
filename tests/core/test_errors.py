from app.core.errors import format_error_response
def test_format_error_response():
    err = format_error_response("Not found", "NOT_FOUND", 404)
    assert err["error"]["code"] == "NOT_FOUND"
