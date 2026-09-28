"""Admissions programs: public catalogue and admin-only mutations."""
import json
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from postgrest.exceptions import APIError

from .rag import valid_url


class MajorInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    admission_code: str = Field(min_length=2, max_length=30, pattern=r'^[A-Z0-9][A-Z0-9_ -]*$')
    major_code: str = Field(min_length=3, max_length=30, pattern=r'^[A-Z0-9_.-]+$')
    name: str = Field(min_length=2, max_length=300)
    program_name: str = Field(min_length=2, max_length=500)
    admission_year: int = Field(ge=2000, le=2100)
    campus: Literal['hanoi', 'hcm']
    quota: int | None = Field(default=None, ge=0, le=100000)
    methods: list[str] = Field(default_factory=list, max_length=20)
    subject_groups: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default='', max_length=10000)
    source_url: str = Field(max_length=2000)
    is_active: bool = True

    @field_validator('subject_groups')
    @classmethod
    def validate_codes(cls, values):
        result = list(dict.fromkeys(v.strip().upper() for v in values))
        if any(not re.fullmatch(r'[A-Z0-9_-]{2,20}', v) for v in result):
            raise ValueError('Mã phương thức/tổ hợp chỉ gồm chữ, số, gạch ngang hoặc gạch dưới.')
        return result

    @field_validator('methods')
    @classmethod
    def validate_methods(cls, values):
        result = list(dict.fromkeys(v.strip() for v in values))
        if any(not v or len(v) > 500 for v in result):
            raise ValueError('Mỗi phương thức cần từ 1 đến 500 ký tự.')
        return result

    @field_validator('source_url')
    @classmethod
    def validate_source(cls, value):
        return valid_url(value)


def parse_catalogue(data):
    if not isinstance(data, dict):
        raise ValueError('JSON phải là một object chứa metadata và chi_tieu_YYYY.')
    sections = [k for k in data if re.fullmatch(r'chi_tieu_20\d{2}', k)]
    if not sections:
        raise ValueError('Không tìm thấy chi_tieu_YYYY trong JSON.')
    source = data.get('metadata', {}).get('source_url', '')
    rows, keys = [], set()
    for section in sections:
        year = int(section[-4:])
        if not isinstance(data[section], dict):
            raise ValueError(f'{section} phải là object.')
        for code, group in data[section].items():
            if code not in {'GHA', 'GSA'}:
                continue
            programs = group.get('programs', [])
            if not isinstance(programs, list):
                raise ValueError(f'{code}.programs phải là danh sách.')
            for index, item in enumerate(programs, 1):
                try:
                    row = MajorInput(
                        admission_code=item['ma_xet_tuyen'], major_code=item['ma_nganh'],
                        name=item['ten_nganh'], program_name=item['ten_chuong_trinh_nganh'],
                        admission_year=year, campus='hanoi' if code == 'GHA' else 'hcm',
                        quota=item.get('chi_tieu_du_kien'),
                        methods=item.get('phuong_thuc_tuyen_sinh', []),
                        subject_groups=item.get('to_hop_mon_pt1_pt2', []),
                        notes=item.get('ghi_chu') or '', source_url=source).model_dump()
                except (KeyError, TypeError, ValidationError) as exc:
                    raise ValueError(f'{code}, dòng {index}: dữ liệu ngành không hợp lệ ({type(exc).__name__}).') from exc
                key = (year, code, row['admission_code'])
                if key in keys:
                    raise ValueError(f'Mã xét tuyển trùng trong tệp: {row["admission_code"]}.')
                keys.add(key)
                rows.append(row)
    if not rows or len(rows) > 1000:
        raise ValueError('JSON phải chứa từ 1 đến 1.000 chương trình.')
    return rows


def make_router(db, admin):
    router = APIRouter(tags=['Ngành học'])

    def listing(q, year, campus, page, page_size, include_hidden=False):
        query = db().table('major_catalogue').select('*', count='exact')
        if not include_hidden:
            query = query.eq('is_active', True)
        if year is not None:
            query = query.eq('admission_year', year)
        if campus:
            query = query.eq('campus', campus)
        if q.strip():
            # Single column filter; escape LIKE metacharacters, no raw OR expression.
            term = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            query = query.ilike('search_text', f'%{term}%')
        result = query.order('admission_year', desc=True).order('admission_code').order('id').range((page-1)*page_size, page*page_size-1).execute()
        return {'items': result.data, 'total': result.count or 0, 'page': page, 'page_size': page_size}

    @router.get('/majors')
    def public_list(q: str = Query(default='', max_length=100), year: int | None = Query(default=None, ge=2000, le=2100),
                    campus: Literal['hanoi', 'hcm'] | None = None, page: int = Query(default=1, ge=1),
                    page_size: int = Query(default=12, ge=1, le=100)):
        return listing(q, year, campus, page, page_size)

    @router.get('/majors/{major_id}')
    def public_detail(major_id: UUID):
        rows = db().table('major_catalogue').select('*').eq('id', str(major_id)).eq('is_active', True).execute().data
        if not rows:
            raise HTTPException(404, 'Không tìm thấy ngành học.')
        return rows[0]

    @router.get('/admin/majors')
    def admin_list(q: str = Query(default='', max_length=100), year: int | None = Query(default=None, ge=2000, le=2100),
                   campus: Literal['hanoi', 'hcm'] | None = None, page: int = Query(default=1, ge=1),
                   page_size: int = Query(default=12, ge=1, le=100), uid=Depends(admin)):
        return listing(q, year, campus, page, page_size, True)

    def save(body, major_id=None):
        try:
            row = db().rpc('save_major', {
                'p_data': body.model_dump(),
                'p_id': str(major_id) if major_id else None
            }).execute().data
        except APIError as exc:
            if exc.code == '23505':
                raise HTTPException(409, 'Mã xét tuyển đã tồn tại trong cùng năm và cơ sở.') from exc
            raise
        if row is None:
            raise HTTPException(404, 'Ngành học không còn tồn tại. Hãy tải lại danh sách.')
        return row

    @router.post('/admin/majors', status_code=201)
    def create(body: MajorInput, uid=Depends(admin)):
        return save(body)

    @router.patch('/admin/majors/{major_id}')
    def update(major_id: UUID, body: MajorInput, uid=Depends(admin)):
        return save(body, major_id)

    @router.delete('/admin/majors/{major_id}')
    def delete(major_id: UUID, uid=Depends(admin)):
        deleted = db().rpc('delete_major', {'p_id': str(major_id)}).execute().data
        if not deleted:
            raise HTTPException(404, 'Ngành học không còn tồn tại.')
        return {'deleted': True}

    @router.post('/admin/majors/import')
    def import_json(file: UploadFile = File(...), uid=Depends(admin)):
        content = file.file.read(2_000_001)
        if len(content) > 2_000_000:
            raise HTTPException(422, 'JSON tối đa 2 MB.')
        try:
            rows = parse_catalogue(json.loads(content.decode('utf-8-sig')))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        # One PostgreSQL transaction; existing admin edits are preserved.
        try:
            return db().rpc('import_majors', {'p_rows': rows}).execute().data
        except APIError as exc:
            if exc.code == '23505':
                raise HTTPException(409, 'JSON chứa mã xét tuyển đã tồn tại trong năm/cơ sở này.') from exc
            raise

    return router
