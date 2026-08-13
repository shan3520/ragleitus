'''JSON document parser service.'''
import json

def parse_json_content(json_text: str) -> dict | list:
    if not json_text:
        return {}
    return json.loads(json_text)
