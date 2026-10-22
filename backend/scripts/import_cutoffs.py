"""Run from backend: .venv/Scripts/python scripts/import_cutoffs.py data/cutoffs_2024_2026.json [--apply]."""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.cutoffs import search_key
from app.localdb import connect


def parse_cutoffs(data):
    if not isinstance(data, dict) or not isinstance(data.get('scores'), list):
        raise ValueError('JSON phải chứa danh sách scores.')
    rows = data['scores']
    if not 1 <= len(rows) <= 10000:
        raise ValueError('Số bản ghi phải từ 1 đến 10.000.')
    keys = set()
    result = []
    for i, row in enumerate(rows, 1):
        try:
            year = row['admission_year']
            campus = row['campus']
            code = row['admission_code']
            name = row['program_name']
            method = row['method']
            score = row['score']
            scale = row['scale']
            url = row['source_url']
            note = row.get('note', '')
            if type(year) is not int or not 2000 <= year <= 2100 or campus not in ('hanoi', 'hcm'):
                raise ValueError('năm hoặc cơ sở không hợp lệ')
            if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{1,39}', code):
                raise ValueError('mã xét tuyển không hợp lệ')
            if not isinstance(name, str) or not 2 <= len(name.strip()) <= 500:
                raise ValueError('tên ngành không hợp lệ')
            if method not in ('PT1', 'PT2', 'PT3', 'PT4'):
                raise ValueError('phương thức không hợp lệ')
            if type(score) not in (int, float) or type(scale) is not int or scale not in (30, 100, 150, 1200) or not 0 < score <= scale:
                raise ValueError('điểm hoặc thang điểm không hợp lệ')
            parts = urlsplit(url)
            if parts.scheme != 'https' or parts.hostname not in ('utc.edu.vn', 'www.utc.edu.vn', 'tuyensinh.utc.edu.vn', 'tuyensinh.utc2.edu.vn'):
                raise ValueError('nguồn phải là trang chính thức của UTC')
            if not isinstance(note, str) or len(note) > 500:
                raise ValueError('ghi chú không hợp lệ')
            key = (year, campus, code, method)
            if key in keys:
                raise ValueError('bản ghi trùng trong tệp')
            keys.add(key)
            result.append((year, campus, code, name.strip(), method, score, scale, url, note, search_key(code+' '+name)))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f'Dòng {i}: {exc}') from exc
    return result


def import_cutoffs(rows):
    from app.v2store import import_cutoff_rows
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        return import_cutoff_rows(conn, rows)



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Kiểm tra hoặc nạp điểm chuẩn vào SQLite mà không ghi đè bản ghi hiện có.')
    parser.add_argument('file')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    rows = parse_cutoffs(json.loads(Path(args.file).read_text(encoding='utf-8-sig')))
    print(json.dumps({'validated':len(rows),'years':dict(Counter(row[0] for row in rows))},ensure_ascii=False))
    if args.apply:
        print(json.dumps(import_cutoffs(rows),ensure_ascii=False))
