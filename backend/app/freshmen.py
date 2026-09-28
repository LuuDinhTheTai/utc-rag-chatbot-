"""K67 newcomer guide. Public read, admin-only writes."""
import logging
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

log = logging.getLogger('utc')
BUCKET = 'admission-documents'
MAX_PDF_BYTES = 10 * 1024 * 1024


class GuideUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    title: str = Field(min_length=5, max_length=300)
    admission_year: int = Field(ge=2000, le=2100)
    is_published: bool = True


class ItemInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    code: str = Field(min_length=1, max_length=20, pattern=r'^[0-9A-Za-z_-]+$')
    category: Literal['document', 'priority']
    title: str = Field(min_length=2, max_length=500)
    applies_to: str = Field(default='', max_length=2000)
    evidence: str = Field(default='', max_length=5000)
    source_page: int = Field(ge=1, le=100)
    sort_order: int = Field(default=0, ge=0, le=10000)
    is_active: bool = True


def make_router(db, admin):
    router = APIRouter(tags=['Tân sinh viên'])

    def guide_for(cohort, published=True):
        query = db().table('freshman_guides').select('*').eq('cohort', cohort.upper())
        if published:
            query = query.eq('is_published', True)
        rows = query.execute().data
        if not rows:
            raise HTTPException(404, 'Không tìm thấy hướng dẫn cho khóa này.')
        return rows[0]

    def items_for(guide_id, include_hidden=False):
        query = db().table('freshman_items').select('*').eq('guide_id', guide_id)
        if not include_hidden:
            query = query.eq('is_active', True)
        return query.order('category').order('sort_order').order('code').limit(500).execute().data

    @router.get('/freshmen')
    def public_guides():
        return db().table('freshman_guides').select('id,cohort,admission_year,title').eq('is_published', True).order('admission_year', desc=True).limit(100).execute().data

    @router.get('/freshmen/{cohort}')
    def public_guide(cohort: str):
        guide = guide_for(cohort)
        return {'guide': {k: v for k, v in guide.items() if k != 'storage_path'}, 'items': items_for(guide['id'])}

    def pdf_response(guide):
        data = db().storage.from_(BUCKET).download(guide['storage_path'])
        return Response(content=data, media_type='application/pdf',
                        headers={'Content-Disposition': 'inline; filename="freshman-guide.pdf"',
                                 'Cache-Control': 'private, max-age=60',
                                 'X-Content-Type-Options': 'nosniff'})

    @router.get('/freshmen/{cohort}/pdf')
    def public_pdf(cohort: str):
        return pdf_response(guide_for(cohort))

    @router.get('/admin/freshmen/{cohort}/pdf')
    def admin_pdf(cohort: str, uid=Depends(admin)):
        return pdf_response(guide_for(cohort, False))

    @router.get('/admin/freshmen')
    def admin_guides(uid=Depends(admin)):
        return db().table('freshman_guides').select('id,cohort,admission_year,title,is_published').order('admission_year', desc=True).limit(100).execute().data

    @router.get('/admin/freshmen/{cohort}')
    def admin_guide(cohort: str, uid=Depends(admin)):
        guide = guide_for(cohort, False)
        return {'guide': guide, 'items': items_for(guide['id'], True)}

    @router.post('/admin/freshmen', status_code=201)
    def create_guide(cohort: str = Form(...), title: str = Form(...), admission_year: int = Form(...),
                     file: UploadFile = File(...), uid=Depends(admin)):
        cohort = cohort.strip().upper()
        if not re.fullmatch(r'K[0-9]{1,4}', cohort):
            raise HTTPException(422, 'Mã khóa có dạng K67.')
        try:
            body = GuideUpdate(title=title, admission_year=admission_year)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_context=False, include_url=False)) from exc
        data = file.file.read(MAX_PDF_BYTES + 1)
        if len(data) > MAX_PDF_BYTES or not data.startswith(b'%PDF-'):
            raise HTTPException(422, 'Chỉ chấp nhận PDF hợp lệ tối đa 10 MB.')
        if db().table('freshman_guides').select('id').eq('cohort', cohort).execute().data:
            raise HTTPException(409, 'Hướng dẫn cho khóa này đã tồn tại.')
        path = f'freshmen/{cohort}/{uuid4()}.pdf'
        db().storage.from_(BUCKET).upload(path, data, {'content-type': 'application/pdf', 'upsert': 'false'})
        try:
            rows = db().table('freshman_guides').insert(body.model_dump() | {'cohort': cohort, 'storage_path': path}).execute().data
        except Exception:
            db().storage.from_(BUCKET).remove([path])
            raise
        return rows[0]

    @router.patch('/admin/freshmen/{cohort}')
    def update_guide(cohort: str, body: GuideUpdate, uid=Depends(admin)):
        guide = guide_for(cohort, False)
        rows = db().table('freshman_guides').update(
            body.model_dump() | {'updated_at': datetime.now(timezone.utc).isoformat()}
        ).eq('id', guide['id']).execute().data
        return rows[0]

    @router.delete('/admin/freshmen/{cohort}')
    def delete_guide(cohort: str, uid=Depends(admin)):
        guide = guide_for(cohort, False)
        db().storage.from_(BUCKET).remove([guide['storage_path']])
        db().table('freshman_guides').delete().eq('id', guide['id']).execute()
        return {'deleted': True}

    def write(query):
        try:
            rows = query.execute().data
        except APIError as exc:
            if exc.code == '23505':
                raise HTTPException(409, 'Mã mục đã tồn tại trong nhóm này.') from exc
            raise
        if not rows:
            raise HTTPException(404, 'Không tìm thấy mục hướng dẫn.')
        return rows[0]

    @router.post('/admin/freshmen/{cohort}/items', status_code=201)
    def create_item(cohort: str, body: ItemInput, uid=Depends(admin)):
        guide = guide_for(cohort, False)
        return write(db().table('freshman_items').insert(body.model_dump() | {'guide_id': guide['id']}))

    @router.patch('/admin/freshmen/{cohort}/items/{item_id}')
    def update_item(cohort: str, item_id: UUID, body: ItemInput, uid=Depends(admin)):
        guide = guide_for(cohort, False)
        return write(db().table('freshman_items').update(
            body.model_dump() | {'updated_at': datetime.now(timezone.utc).isoformat()}
        ).eq('id', str(item_id)).eq('guide_id', guide['id']))

    @router.delete('/admin/freshmen/{cohort}/items/{item_id}')
    def delete_item(cohort: str, item_id: UUID, uid=Depends(admin)):
        guide = guide_for(cohort, False)
        write(db().table('freshman_items').delete().eq('id', str(item_id)).eq('guide_id', guide['id']))
        return {'deleted': True}

    return router
