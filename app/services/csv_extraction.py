'''CSV document parser service.'''
import csv
import io

def parse_csv_content(csv_text: str) -> list[dict]:
    if not csv_text:
        return []
    reader = csv.DictReader(io.StringIO(csv_text))
    return [row for row in reader]
