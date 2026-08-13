from app.services.html_extraction import strip_html_tags
def test_strip_html_tags():
    assert strip_html_tags("<h1>Title</h1><p>Paragraph</p>") == "Title Paragraph"
