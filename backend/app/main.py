import hashlib
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import lru_cache
from typing import Literal
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from google.genai.errors import APIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from supabase import create_client

from .config import settings
from .rag import MAX_BYTES, NO_ANSWER, chunks, embeddings, extract, fetch_url, filters, generate, valid_url

logging.basicConfig(level=logging.INFO)
# Signed Storage URLs are bearer credentials; do not log HTTP request URLs.
logging.getLogger('httpx').setLevel(logging.WARNING)
log = logging.getLogger('utc')
app = FastAPI(title='UTC Admissions RAG', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=[settings().frontend_origin], allow_methods=['GET', 'POST', 'PATCH', 'DELETE'], allow_headers=['Content-Type', 'Authorization', 'X-Session-Token'])


@lru_cache
def db():
    cfg = settings()
    if not cfg.supabase_url or not cfg.supabase_secret_key:
        raise HTTPException(503, 'Chưa cấu hình Supabase trên máy chủ.')
    return create_client(cfg.supabase_url, cfg.supabase_secret_key)


def admin(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Vui lòng đăng nhập.')
    try:
        user = db().auth.get_user(authorization[7:]).user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, 'Phiên đăng nhập không hợp lệ.')
    if not user or user.app_metadata.get('role') != 'admin':
        raise HTTPException(403, 'Tài khoản không có quyền quản trị.')
    return str(user.id)


def session(x_session_token: str = Header(default='')):
    if not 32 <= len(x_session_token) <= 200:
        raise HTTPException(401, 'Phiên trò chuyện không hợp lệ.')
    rows = db().table('chat_sessions').select('id').eq('token_hash', hashlib.sha256(x_session_token.encode()).hexdigest()).execute().data
    if not rows:
        raise HTTPException(401, 'Phiên trò chuyện không tồn tại.')
    return rows[0]['id']


rates = defaultdict(deque)
rate_lock = threading.Lock()


def throttle(request: Request):
    key = request.client.host if request.client else 'unknown'
    now = time.monotonic()
    with rate_lock:
        for old in list(rates):
            while rates[old] and now - rates[old][0] > 60:
                rates[old].popleft()
            if not rates[old]:
                del rates[old]
        if len(rates[key]) >= 20:
            raise HTTPException(429, 'Bạn gửi quá nhanh. Vui lòng thử lại sau một phút.')
        rates[key].append(now)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Never log or return the rejected document text, credentials or request body.
    errors = [{'loc': list(error['loc']), 'type': error['type'], 'msg': error['msg'],
               'ctx': {key: value for key, value in error.get('ctx', {}).items()
                       if key in {'min_length', 'max_length', 'ge', 'le'} and isinstance(value, (int, float))}}
              for error in exc.errors()]
    log.warning('validation_failed path=%s fields=%s', request.url.path,
                [(error['loc'], error['type']) for error in errors])
    return JSONResponse(status_code=422, content={'detail': errors})


@app.exception_handler(APIError)
async def gemini_error(request, exc):
    log.warning('gemini_request_failed path=%s status=%s', request.url.path, exc.code)
    if exc.code == 429:
        message = 'Gemini đang giới hạn lượt gọi hoặc đã hết hạn mức. Vui lòng thử lại sau; quản trị viên cần kiểm tra quota nếu lỗi tiếp diễn.'
    elif exc.code in {408, 500, 502, 503, 504}:
        message = 'Gemini đang quá tải hoặc tạm thời gián đoạn. Vui lòng đợi khoảng 30 giây rồi gửi lại câu hỏi.'
    else:
        message = 'Không thể gọi Gemini. Quản trị viên cần kiểm tra API key, quyền truy cập và model đã cấu hình.'
    transient = exc.code in {408, 429, 500, 502, 503, 504}
    return JSONResponse(status_code=503 if transient else 502,
                        headers={'Retry-After': '30'} if transient else {},
                        content={'detail': message})


@app.exception_handler(Exception)
async def unexpected(request, exc):
    log.error('request_failed path=%s type=%s', request.url.path, type(exc).__name__)
    return JSONResponse(status_code=503, content={'detail': 'Dịch vụ tạm thời không khả dụng. Vui lòng thử lại sau.'})


@app.get('/health')
def health():
    cfg = settings()
    return {'status': 'ok', 'configured': bool(cfg.supabase_url and cfg.supabase_secret_key and cfg.google_api_key)}


@app.post('/sessions', dependencies=[Depends(throttle)])
def new_session():
    token = secrets.token_urlsafe(32)
    row = db().table('chat_sessions').insert({'token_hash': hashlib.sha256(token.encode()).hexdigest()}).execute().data[0]
    return {'id': row['id'], 'token': token}


@app.get('/messages')
def history(sid=Depends(session)):
    return db().table('messages').select('*').eq('session_id', sid).order('created_at').limit(200).execute().data


class ChatInput(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    year: int = Field(default=2026, ge=2000, le=2100)
    campus: Literal['hanoi', 'hcm'] = 'hanoi'


@app.post('/chat', dependencies=[Depends(throttle)])
def chat(body: ChatInput, sid=Depends(session)):
    question = body.question.strip()
    if len(question) < 2:
        raise HTTPException(422, 'Vui lòng nhập câu hỏi.')
    started = time.monotonic()
    try:
        year, campus = filters(question, body.year, body.campus)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not settings().google_api_key:
        raise HTTPException(503, 'Chưa cấu hình Gemini API trên máy chủ.')
    vector = embeddings().embed_query(question)
    matches = db().rpc('match_chunks', {'query_embedding': vector, 'filter_year': year, 'filter_campus': campus, 'min_similarity': settings().similarity_threshold, 'match_count': 6}).execute().data
    answer, sources, supported = generate(question, matches) if matches else (NO_ANSWER, [], False)
    elapsed = round((time.monotonic() - started) * 1000)
    rows = db().table('messages').insert([
        {'session_id': sid, 'role': 'user', 'content': question, 'sources': [], 'question': None, 'supported': None, 'latency_ms': None},
        {'session_id': sid, 'role': 'assistant', 'question': question, 'content': answer, 'sources': sources, 'supported': supported, 'latency_ms': elapsed}
    ]).execute().data
    log.info('chat_completed latency_ms=%d supported=%s', elapsed, supported)
    return next(row for row in rows if row['role'] == 'assistant')


class FeedbackInput(BaseModel):
    message_id: UUID
    rating: Literal[-1, 1]
    comment: str = Field(default='', max_length=1000)


@app.post('/feedback', dependencies=[Depends(throttle)])
def feedback(body: FeedbackInput, sid=Depends(session)):
    rows = db().table('messages').select('id').eq('id', str(body.message_id)).eq('session_id', sid).eq('role', 'assistant').execute().data
    if not rows:
        raise HTTPException(404, 'Không tìm thấy câu trả lời trong phiên này.')
    return db().table('feedback').upsert(body.model_dump(mode='json'), on_conflict='message_id').execute().data[0]


def ingest(document_id, text):
    try:
        parts = chunks(text)
        if len(parts) > 2000:
            raise ValueError('Tài liệu quá dài; hãy chia thành các tệp nhỏ hơn.')
        model = embeddings()
        for start in range(0, len(parts), 32):
            batch = parts[start:start+32]
            vectors = model.embed_documents(batch)
            db().table('document_chunks').insert([{'document_id': document_id, 'chunk_index': start+i, 'content': content, 'embedding': vector} for i, (content, vector) in enumerate(zip(batch, vectors))]).execute()
        db().table('documents').update({'status': 'ready', 'chunk_count': len(parts), 'error': None}).eq('id', document_id).execute()
    except Exception as exc:
        log.error('ingestion_failed document_id=%s type=%s', document_id, type(exc).__name__)
        db().table('document_chunks').delete().eq('document_id', document_id).execute()
        db().table('documents').update({'status': 'failed', 'error': 'Lập chỉ mục thất bại. Kiểm tra cấu hình, hạn mức API rồi thử lại.'}).eq('id', document_id).execute()


@app.post('/admin/documents/preview')
def preview(file: UploadFile | None = File(default=None), url: str = Form(default=''), uid=Depends(admin)):
    try:
        if file:
            text = extract(file.file.read(MAX_BYTES+1), file.filename or '')
        elif url:
            text = fetch_url(url)
        else:
            raise ValueError('Chọn tệp hoặc nhập URL.')
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, str(exc))
    return {'text': text, 'characters': len(text), 'chunks': len(chunks(text))}


class DocumentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=300)
    source_url: str = Field(max_length=2000)
    admission_year: int = Field(ge=2000, le=2100)
    campus: Literal['hanoi', 'hcm']
    category: str = Field(default='tuyen-sinh', max_length=100)
    text: str = Field(min_length=30, max_length=2_000_000)


STORAGE_BUCKET = 'admission-documents'


def persist_document(body, tasks, uid, original=None):
    try:
        valid_url(body.source_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    checksum = hashlib.sha256(f'{body.admission_year}:{body.campus}:{body.text}'.encode()).hexdigest()
    if db().table('documents').select('id').eq('checksum', checksum).execute().data:
        raise HTTPException(409, 'Tài liệu này đã tồn tại cho năm và cơ sở đã chọn.')
    document_id = str(uuid4())
    values = body.model_dump(exclude={'text'}) | {'id': document_id, 'raw_text': body.text, 'checksum': checksum, 'status': 'processing', 'created_by': uid}
    path = None
    if original:
        data, filename, mime = original
        suffix = filename.rsplit('.', 1)[-1].lower()
        path = f'{document_id}/original.{suffix}'
        db().storage.from_(STORAGE_BUCKET).upload(path, data, {'content-type': mime, 'upsert': 'false'})
        values.update(storage_path=path, original_filename=filename, original_size=len(data))
    try:
        row = db().table('documents').insert(values).execute().data[0]
    except Exception:
        if path:
            try:
                db().storage.from_(STORAGE_BUCKET).remove([path])
            except Exception:
                log.error('storage_cleanup_failed document_id=%s', document_id)
        raise
    tasks.add_task(ingest, row['id'], body.text)
    return {'id': row['id'], 'status': row['status']}


@app.post('/admin/documents')
def create_document(body: DocumentInput, tasks: BackgroundTasks, uid=Depends(admin)):
    return persist_document(body, tasks, uid)


@app.post('/admin/documents/upload')
def upload_document(tasks: BackgroundTasks, metadata: str = Form(...),
                    file: UploadFile = File(...), uid=Depends(admin)):
    try:
        body = DocumentInput.model_validate_json(metadata)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors())
    filename = (file.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
    if len(filename) > 255:
        raise HTTPException(422, 'Tên tệp tối đa 255 ký tự.')
    data = file.file.read(MAX_BYTES + 1)
    try:
        extract(data, filename)
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, str(exc))
    suffix = filename.rsplit('.', 1)[-1].lower()
    mime = {'pdf': 'application/pdf', 'txt': 'text/plain', 'md': 'text/markdown'}[suffix]
    return persist_document(body, tasks, uid, (data, filename, mime))


@app.get('/admin/documents/{document_id}/download')
def download_document(document_id: UUID, uid=Depends(admin)):
    rows = db().table('documents').select('storage_path,original_filename,status').eq('id', str(document_id)).execute().data
    if not rows or not rows[0].get('storage_path') or rows[0]['status'] == 'deleting':
        raise HTTPException(404, 'Tài liệu này không có tệp gốc để tải xuống.')
    row = rows[0]
    result = db().storage.from_(STORAGE_BUCKET).create_signed_url(
        row['storage_path'], 60, {'download': row['original_filename'] or True})
    return {'url': result['signedURL'], 'expires_in': 60}


@app.get('/admin/documents')
def documents(uid=Depends(admin)):
    return db().table('documents').select('id,title,source_url,admission_year,campus,category,status,chunk_count,error,created_at,storage_path,original_filename,original_size').order('created_at', desc=True).limit(200).execute().data


class DocumentStatus(BaseModel):
    status: Literal['ready', 'inactive']


@app.patch('/admin/documents/{document_id}')
def toggle(document_id: UUID, body: DocumentStatus, uid=Depends(admin)):
    rows = db().table('documents').update({'status': body.status}).eq('id', str(document_id)).in_('status', ['ready', 'inactive']).execute().data
    if not rows:
        raise HTTPException(409, 'Chỉ bật/tắt được tài liệu đã lập chỉ mục.')
    return {'status': body.status}


@app.post('/admin/documents/{document_id}/retry')
def retry(document_id: UUID, tasks: BackgroundTasks, uid=Depends(admin)):
    rows = db().table('documents').update({'status': 'processing', 'error': None}).eq('id', str(document_id)).eq('status', 'failed').execute().data
    if not rows:
        raise HTTPException(409, 'Chỉ thử lại tài liệu bị lỗi.')
    db().table('document_chunks').delete().eq('document_id', str(document_id)).execute()
    tasks.add_task(ingest, str(document_id), rows[0]['raw_text'])
    return {'status': 'processing'}


@app.delete('/admin/documents/{document_id}')
def delete_document(document_id: UUID, uid=Depends(admin)):
    # Claim the row so retry/toggle cannot start ingestion during removal.
    rows = db().table('documents').update({'status': 'deleting'}).eq('id', str(document_id)).in_('status', ['ready', 'inactive', 'failed', 'deleting']).execute().data
    if not rows:
        raise HTTPException(409, 'Tài liệu không tồn tại hoặc đang được xử lý.')
    if rows[0].get('storage_path'):
        db().storage.from_(STORAGE_BUCKET).remove([rows[0]['storage_path']])
    db().table('documents').delete().eq('id', str(document_id)).eq('status', 'deleting').execute()
    return {'deleted': True}


@app.get('/admin/review')
def review(uid=Depends(admin)):
    return {'unanswered': db().table('messages').select('*').eq('role', 'assistant').eq('supported', False).order('created_at', desc=True).limit(100).execute().data,
            'feedback': db().table('feedback').select('*,messages(content,sources)').order('created_at', desc=True).limit(100).execute().data}


from .majors import make_router
app.include_router(make_router(db, admin))

from .freshmen import make_router as make_freshmen_router
app.include_router(make_freshmen_router(db, admin))
