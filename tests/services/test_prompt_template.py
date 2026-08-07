from app.services.prompt_template import format_prompt
def test_format_prompt():
    assert format_prompt("Hello {name}", {"name": "World"}) == "Hello World"
    assert format_prompt("", {}) == ""
