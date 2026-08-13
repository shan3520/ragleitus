'''Markdown document parser service.'''
def parse_markdown_headers(md_text: str) -> list[dict]:
    if not md_text:
        return []
    sections = []
    current_title = "Intro"
    current_lines = []

    for line in md_text.splitlines():
        if line.startswith("#"):
            if current_lines:
                sections.append({"header": current_title, "content": "\n".join(current_lines).strip()})
                current_lines = []
            current_title = line.lstrip("#").strip()
        else:
            current_lines.append(line)

    if current_lines or current_title:
        sections.append({"header": current_title, "content": "\n".join(current_lines).strip()})

    return sections
