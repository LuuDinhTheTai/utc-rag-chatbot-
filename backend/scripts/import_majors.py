"""Run from backend: .venv/Scripts/python scripts/import_majors.py FILE [--apply]."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.majors import parse_catalogue
from app.main import db

parser = argparse.ArgumentParser(description='Validate/import UTC admissions JSON without overwriting existing rows.')
parser.add_argument('file')
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
rows = parse_catalogue(json.loads(Path(args.file).read_text(encoding='utf-8-sig')))
print(json.dumps({'validated': len(rows), 'campuses': dict(Counter(row['campus'] for row in rows))}))
if args.apply:
    result = db().rpc('import_majors', {'p_rows': rows}).execute().data
    print(json.dumps(result))
