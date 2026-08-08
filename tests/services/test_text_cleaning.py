from app.services.text_cleaning import clean_text_pages


def test_clean_text_pages_collapses_whitespace_and_strips_controls():
    pages = ["Hello\tworld\n", "Line\x0c  two\r\n"]

    assert clean_text_pages(pages) == ["Hello world", "Line two"]


def test_clean_text_pages_removes_repeating_headers_and_footers():
    pages = [
        "Report Title\nPage 1\nContent A\nFooter text",
        "Report Title\nPage 2\nContent B\nFooter text",
        "Report Title\nPage 3\nContent C\nFooter text",
    ]

    assert clean_text_pages(pages) == ["Page 1 Content A", "Page 2 Content B", "Page 3 Content C"]
