"""Public lookup for official historical UTC admission cutoff scores."""
import unicodedata
from typing import Literal

from fastapi import APIRouter, Query

from .localdb import connect
from .v2store import relation

CUTOFFS = relation("cutoff_scores")

router = APIRouter(tags=['Điểm chuẩn'])


def search_key(value: str) -> str:
    text = unicodedata.normalize('NFD', value.casefold())
    return ''.join(char for char in text if unicodedata.category(char) != 'Mn').replace('đ', 'd')


@router.get('/cutoffs/options')
def options():
    with connect() as conn:
        years = [row[0] for row in conn.execute(f'SELECT DISTINCT admission_year FROM {CUTOFFS} ORDER BY admission_year DESC')]
        methods = [row[0] for row in conn.execute(f'SELECT DISTINCT method FROM {CUTOFFS} ORDER BY method')]
        majors = [row[0] for row in conn.execute(f'SELECT DISTINCT program_name FROM {CUTOFFS} ORDER BY program_name COLLATE NOCASE')]
    return {'years': years, 'methods': methods, 'majors': majors}


@router.get('/cutoffs')
def list_cutoffs(
    q: str = Query(default='', max_length=100),
    major: str = Query(default='', max_length=500),
    admission_code: str = Query(default='', max_length=30),
    year: int | None = Query(default=None, ge=2000, le=2100),
    campus: Literal['hanoi', 'hcm'] | None = None,
    method: Literal['PT1', 'PT2', 'PT3', 'PT4'] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    terms = []
    values = []
    if q.strip():
        term = search_key(q.strip()).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        terms.append("search_text LIKE ? ESCAPE '\\'")
        values.append('%' + term + '%')
    if major:
        terms.append('program_name = ?')
        values.append(major)
    if admission_code:
        terms.append('admission_code = ?')
        values.append(admission_code)
    if year is not None:
        terms.append('admission_year = ?')
        values.append(year)
    if campus:
        terms.append('campus = ?')
        values.append(campus)
    if method:
        terms.append('method = ?')
        values.append(method)
    where = ' WHERE ' + ' AND '.join(terms) if terms else ''
    with connect() as conn:
        total = conn.execute(f'SELECT count(*) FROM {CUTOFFS}' + where, values).fetchone()[0]
        records = conn.execute(f'SELECT admission_year,campus,admission_code,program_name,method,score,scale,source_url,note FROM {CUTOFFS}' + where + ' ORDER BY admission_year DESC,campus,admission_code,method LIMIT ? OFFSET ?', values + [page_size, (page-1)*page_size]).fetchall()
    return {'items': [dict(row) for row in records], 'total': total, 'page': page, 'page_size': page_size}
