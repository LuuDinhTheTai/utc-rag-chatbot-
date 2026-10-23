"""Personal admissions planning and a deliberately scoped score calculator."""
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import authenticated, owner
from .localdb import connect, now
from .rag import valid_url

router = APIRouter(tags=['Kế hoạch tuyển sinh'])
Year = Annotated[int, Field(ge=2000, le=2100)]
Mark = Annotated[Decimal, Field(ge=0, le=10, decimal_places=2)]
Priority = Annotated[Decimal, Field(ge=0, le=5, decimal_places=2)]
Bonus = Annotated[Decimal, Field(ge=0, le=3, decimal_places=2)]
Weight = Annotated[Decimal, Field(gt=0, le=3, decimal_places=2)]
DueDate = Annotated[date, Field(ge=date(2000,1,1), le=date(2100,12,31))]
Campus = Literal['hanoi','hcm']
Method = Literal['PT1','PT2','PT3','PT4']


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class RuleInput(Input):
    title: str = Field(min_length=3,max_length=200)
    admission_year: Year
    campus: Campus
    subject_group: str = Field(pattern=r'^[A-Z0-9_-]{2,20}$')
    subjects: list[str] = Field(min_length=3,max_length=3)
    weights: list[Weight] = Field(min_length=3,max_length=3)
    priority_mode: Literal['none','provided','taper_30'] = 'provided'
    priority_cap: Priority = Decimal('0')
    bonus_cap: Bonus = Decimal('0')
    source_url: str = Field(max_length=2000)
    scope_note: str = Field(min_length=10,max_length=2000)
    source_reviewed: Literal[True]

    @field_validator('subjects')
    @classmethod
    def subjects_valid(cls, values):
        values = [v.strip() for v in values]
        if len(set(values)) != 3 or any(not v or len(v)>80 for v in values):
            raise ValueError('Cần ba môn khác nhau, mỗi tên tối đa 80 ký tự.')
        return values

    @field_validator('source_url')
    @classmethod
    def official_source(cls,value):
        return valid_url(value)


def rule_json(row):
    record = dict(row)
    record['subjects'] = [record.pop(f'subject_{i}') for i in range(1,4)]
    record['weights'] = [record.pop(f'weight_{i}') for i in range(1,4)]
    record['is_active'] = bool(record['is_active'])
    return record


@router.get('/score-rules')
def score_rules(year: Year = 2026, campus: Campus = 'hanoi'):
    with connect() as conn:
        return [rule_json(r) for r in conn.execute('SELECT * FROM admission_score_rules WHERE admission_year=? AND campus=? AND is_active=1 ORDER BY created_at,id',(year,campus))]


@router.post('/admin/score-rules',status_code=201)
def publish_rule(body:RuleInput, uid=Depends(owner)):
    identifier = str(uuid4())
    with connect() as conn:
        conn.execute('INSERT INTO admission_score_rules VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)',
                     (identifier,body.title,body.admission_year,body.campus,body.subject_group,*body.subjects,
                      *(float(w) for w in body.weights),body.priority_mode,float(body.priority_cap),float(body.bonus_cap),
                      body.source_url,body.scope_note,uid,now()))
        return rule_json(conn.execute('SELECT * FROM admission_score_rules WHERE id=?',(identifier,)).fetchone())


@router.delete('/admin/score-rules/{rule_id}')
def revoke_rule(rule_id:UUID,uid=Depends(owner)):
    with connect() as conn:
        if not conn.execute('UPDATE admission_score_rules SET is_active=0 WHERE id=? AND is_active=1',(str(rule_id),)).rowcount:
            raise HTTPException(404,'Không tìm thấy công thức đang sử dụng.')
    return {'revoked':True}


class Calculation(Input):
    year: Year
    campus: Campus
    rule_id: UUID | None = None
    scores: list[Mark] = Field(min_length=3,max_length=3)
    priority: Priority = Decimal('0')
    bonus: Bonus = Decimal('0')


def rounded(value):
    return str(value.quantize(Decimal('.01'),rounding=ROUND_HALF_UP))


@router.post('/score-calculations')
def calculate(body:Calculation):
    rule = None
    if body.rule_id:
        with connect() as conn:
            row = conn.execute('SELECT * FROM admission_score_rules WHERE id=? AND is_active=1',(str(body.rule_id),)).fetchone()
            if not row:
                raise HTTPException(404,'Công thức đã bị thu hồi hoặc không tồn tại. Chọn lại công thức.')
            rule = rule_json(row)
        if rule['admission_year'] != body.year or rule['campus'] != body.campus:
            raise HTTPException(422,'Công thức không áp dụng cho năm/cơ sở đã chọn.')
    weights = [Decimal(str(v)) for v in rule['weights']] if rule else [Decimal(1)]*3
    if rule and (body.priority>Decimal(str(rule['priority_cap'])) or body.bonus>Decimal(str(rule['bonus_cap']))):
        raise HTTPException(422,'Điểm ưu tiên/điểm cộng vượt mức của công thức đã chọn.')
    base = sum(s*w for s,w in zip(body.scores,weights))*3/sum(weights)
    priority = body.priority
    mode = rule['priority_mode'] if rule else 'provided'
    if mode == 'none' and priority:
        raise HTTPException(422,'Công thức này không áp dụng điểm ưu tiên.')
    if mode == 'taper_30':
        # This supported formula uses the normalized subject total, BEFORE bonus.
        priority *= min(Decimal(1),max(Decimal(0),(30-base)/Decimal('7.5')))
    total = min(Decimal(30),base+body.bonus+priority)
    return {'base':rounded(base),'priority_applied':rounded(priority),'bonus':rounded(body.bonus),
            'total':rounded(total),'scale':30,'year':body.year,'campus':body.campus,'method':'PT1',
            'rule':rule,'mode':'published' if rule else 'manual',
            'formula':'Tổng (điểm môn × hệ số) × 3 / tổng hệ số; cộng ưu tiên và điểm cộng; tối đa 30.',
            'priority_formula':'ƯT × min(1, max(0, (30 − điểm môn đã chuẩn hóa) / 7,5))' if mode=='taper_30' else 'Điểm ưu tiên đã điều chỉnh do bạn nhập.',
            'notice':'Kết quả tham khảo, không xác nhận đủ điều kiện hay trúng tuyển. Không tự quy đổi học bạ, chứng chỉ, điểm ĐGNL hoặc ĐGTD.'}


class PreferenceInput(Input):
    offering_id: UUID
    revision: int = Field(ge=0)
    method: Method = 'PT1'
    subject_group: str = Field(default='',max_length=20)
    notes: str = Field(default='',max_length=2000)


class PreferenceUpdate(Input):
    revision: int = Field(ge=0)
    method: Method
    subject_group: str = Field(default='',max_length=20)
    notes: str = Field(default='',max_length=2000)
    estimated_score: Annotated[Decimal,Field(ge=0,le=1200,decimal_places=2)] | None = None
    score_scale: Literal[30,100,150,1200] = 30


class Reorder(Input):
    year: Year
    revision: int = Field(ge=0)
    ids: list[UUID] = Field(max_length=50)


def revision(conn,uid):
    row = conn.execute('SELECT revision FROM planner_revisions WHERE account_id=?',(uid,)).fetchone()
    return row[0] if row else 0


def change_revision(conn,uid,expected):
    conn.execute('BEGIN IMMEDIATE')
    conn.execute('INSERT INTO planner_revisions(account_id) VALUES (?) ON CONFLICT DO NOTHING',(uid,))
    if not conn.execute('UPDATE planner_revisions SET revision=revision+1 WHERE account_id=? AND revision=?',(uid,expected)).rowcount:
        raise HTTPException(409,'Danh sách đã thay đổi ở một phiên khác. Tải lại trước khi sửa.')


def own_preference(conn,uid,identifier):
    row = conn.execute('SELECT * FROM planner_preferences WHERE id=? AND account_id=?',(str(identifier),uid)).fetchone()
    if not row:
        raise HTTPException(404,'Không tìm thấy nguyện vọng.')
    return row


@router.get('/planner/preferences')
def preferences(year:Year=2026,account=Depends(authenticated)):
    uid = account['id']
    with connect() as conn:
        # One read snapshot pairs items and revision even during concurrent writes.
        conn.execute('BEGIN')
        items = []
        for row in conn.execute('SELECT p.*,CASE WHEN m.is_active=1 AND o.admission_year=p.admission_year AND o.campus_code=p.campus AND o.admission_code=p.admission_code THEN 1 ELSE 0 END AS available FROM planner_preferences p LEFT JOIN major_catalogue m ON m.id=p.offering_id LEFT JOIN admission_offerings o ON o.id=p.offering_id WHERE p.account_id=? AND p.admission_year=? ORDER BY position,id',(uid,year)):
            item = dict(row)
            item['available'] = bool(item['available'])
            item['cutoffs'] = [dict(c) for c in conn.execute('SELECT o.admission_year,c.method_code AS method,c.score,c.scale,c.source_url,c.program_name_snapshot AS program_name FROM cutoff_scores c JOIN admission_offerings o ON o.id=c.offering_id WHERE o.admission_code=? AND o.campus_code=? ORDER BY o.admission_year DESC,c.method_code',(row['admission_code'],row['campus']))]
            items.append(item)
        return {'items':items,'revision':revision(conn,uid)}


@router.post('/planner/preferences',status_code=201)
def add_preference(body:PreferenceInput,account=Depends(authenticated)):
    uid = account['id']
    with connect() as conn:
        change_revision(conn,uid,body.revision)
        row = conn.execute('SELECT o.*,m.source_url FROM admission_offerings o JOIN major_catalogue m ON m.id=o.id WHERE o.id=? AND m.is_active=1',(str(body.offering_id),)).fetchone()
        if not row:
            raise HTTPException(404,'Chương trình không còn hiển thị trong danh mục.')
        existing = conn.execute('SELECT count(*),coalesce(max(position),0) FROM planner_preferences WHERE account_id=? AND admission_year=?',(uid,row['admission_year'])).fetchone()
        if existing[0]>=50:
            raise HTTPException(422,'Tối đa 50 nguyện vọng mỗi năm trong công cụ lập kế hoạch.')
        identifier = str(uuid4())
        try:
            conn.execute('INSERT INTO planner_preferences VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (identifier,uid,row['id'],row['admission_year'],row['campus_code'],row['admission_code'],row['program_name'],row['source_url'],existing[1]+1,body.method,body.subject_group,body.notes,None,30,now(),now()))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409,'Chương trình đã có trong danh sách nguyện vọng.') from exc
        return {'id':identifier,'revision':revision(conn,uid)}


@router.patch('/planner/preferences/{preference_id}')
def edit_preference(preference_id:UUID,body:PreferenceUpdate,account=Depends(authenticated)):
    uid = account['id']
    if body.estimated_score is not None and body.estimated_score>body.score_scale:
        raise HTTPException(422,'Điểm không được vượt thang điểm đã chọn.')
    with connect() as conn:
        change_revision(conn,uid,body.revision)
        own_preference(conn,uid,preference_id)
        conn.execute('UPDATE planner_preferences SET method=?,subject_group=?,notes=?,estimated_score=?,score_scale=?,updated_at=? WHERE id=? AND account_id=?',
                     (body.method,body.subject_group,body.notes,float(body.estimated_score) if body.estimated_score is not None else None,body.score_scale,now(),str(preference_id),uid))
        return {'revision':revision(conn,uid)}


@router.post('/planner/preferences/reorder')
def reorder_preferences(body:Reorder,account=Depends(authenticated)):
    uid = account['id']
    ids = [str(i) for i in body.ids]
    with connect() as conn:
        change_revision(conn,uid,body.revision)
        current = conn.execute('SELECT id,position FROM planner_preferences WHERE account_id=? AND admission_year=?',(uid,body.year)).fetchall()
        if len(ids)!=len(set(ids)) or set(ids)!={r['id'] for r in current}:
            raise HTTPException(422,'Cần gửi đầy đủ mỗi nguyện vọng đúng một lần cho năm đã chọn.')
        offset = max((r['position'] for r in current),default=0)+1
        conn.execute('UPDATE planner_preferences SET position=position+? WHERE account_id=? AND admission_year=?',(offset,uid,body.year))
        for position,identifier in enumerate(ids,1):
            conn.execute('UPDATE planner_preferences SET position=?,updated_at=? WHERE id=? AND account_id=?',(position,now(),identifier,uid))
        return {'revision':revision(conn,uid)}


@router.delete('/planner/preferences/{preference_id}')
def delete_preference(preference_id:UUID,expected_revision:int=Query(ge=0,alias='revision'),account=Depends(authenticated)):
    uid = account['id']
    with connect() as conn:
        change_revision(conn,uid,expected_revision)
        own_preference(conn,uid,preference_id)
        conn.execute('DELETE FROM planner_preferences WHERE id=? AND account_id=?',(str(preference_id),uid))
        return {'revision':revision(conn,uid)}


class TaskInput(Input):
    admission_year: Year
    title: str = Field(min_length=2,max_length=200)
    description: str = Field(default='',max_length=2000)
    due_date: DueDate | None = None
    source_url: str = Field(default='',max_length=2000)

    @field_validator('source_url')
    @classmethod
    def link(cls,value):
        if value:
            parsed = urlsplit(value)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Liên kết nguồn cần dùng HTTPS, không chứa thông tin đăng nhập.')
        return value


class TaskUpdate(Input):
    title: str | None = Field(default=None,min_length=2,max_length=200)
    description: str | None = Field(default=None,max_length=2000)
    due_date: DueDate | None = None
    source_url: str | None = Field(default=None,max_length=2000)
    completed: bool | None = None


class Templates(Input):
    year: Year


TEMPLATES = [
    ('explore','Tìm hiểu ngành và phương thức xét tuyển','Đọc điều kiện tuyển sinh của đúng năm và cơ sở.'),
    ('evidence','Chuẩn bị minh chứng và hồ sơ','Đối chiếu hướng dẫn chính thức; kiểm tra giấy tờ ưu tiên nếu có.'),
    ('preferences','Rà soát thứ tự nguyện vọng','Sắp xếp theo mong muốn học thực tế và kiểm tra mã xét tuyển.'),
    ('confirm','Theo dõi kết quả và xác nhận nhập học','Tự đặt hạn theo thông báo chính thức khi được công bố.'),
    ('enrol','Chuẩn bị hồ sơ nhập học','Đối chiếu thông báo nhập học chính thức dành cho khóa của bạn.'),
]


def task_json(row):
    record = dict(row)
    record['completed'] = bool(record['completed'])
    return record


def task_limit(conn,uid,year,additional=1):
    count = conn.execute('SELECT count(*) FROM planner_tasks WHERE account_id=? AND admission_year=?',(uid,year)).fetchone()[0]
    if count+additional>200:
        raise HTTPException(422,'Tối đa 200 công việc mỗi năm.')


@router.get('/planner/checklist')
def checklist(year:Year=2026,account=Depends(authenticated)):
    with connect() as conn:
        return [task_json(r) for r in conn.execute('SELECT * FROM planner_tasks WHERE account_id=? AND admission_year=? ORDER BY completed,due_date IS NULL,due_date,created_at,id',(account['id'],year))]


@router.post('/planner/checklist',status_code=201)
def add_task(body:TaskInput,account=Depends(authenticated)):
    identifier = str(uuid4())
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        task_limit(conn,account['id'],body.admission_year)
        conn.execute('INSERT INTO planner_tasks VALUES (?,?,?,?,?,?,0,?,NULL,?,?)',
                     (identifier,account['id'],body.admission_year,body.title,body.description,body.due_date.isoformat() if body.due_date else None,body.source_url,now(),now()))
        return task_json(conn.execute('SELECT * FROM planner_tasks WHERE id=?',(identifier,)).fetchone())


@router.post('/planner/checklist/templates')
def add_templates(body:Templates,account=Depends(authenticated)):
    uid = account['id']
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        existing = {r[0] for r in conn.execute('SELECT template_key FROM planner_tasks WHERE account_id=? AND admission_year=?',(uid,body.year))}
        pending = [t for t in TEMPLATES if t[0] not in existing]
        task_limit(conn,uid,body.year,len(pending))
        for key,title,description in pending:
            conn.execute('INSERT INTO planner_tasks VALUES (?,?,?,?,?,NULL,0,?,?,?,?)',
                         (str(uuid4()),uid,body.year,title,description,'',key,now(),now()))
    return {'inserted':len(pending)}


@router.patch('/planner/checklist/{task_id}')
def edit_task(task_id:UUID,body:TaskUpdate,account=Depends(authenticated)):
    changes = body.model_dump(exclude_unset=True)
    if not changes or any(v is None for k,v in changes.items() if k!='due_date'):
        raise HTTPException(422,'Cần cung cấp dữ liệu cập nhật hợp lệ.')
    if 'source_url' in changes:
        try:
            changes['source_url'] = TaskInput.link(changes['source_url'])
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
    if isinstance(changes.get('due_date'),date):
        changes['due_date'] = changes['due_date'].isoformat()
    changes['updated_at'] = now()
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if not conn.execute('SELECT 1 FROM planner_tasks WHERE id=? AND account_id=?',(str(task_id),account['id'])).fetchone():
            raise HTTPException(404,'Không tìm thấy công việc.')
        conn.execute('UPDATE planner_tasks SET '+','.join(f'{k}=?' for k in changes)+' WHERE id=? AND account_id=?',(*changes.values(),str(task_id),account['id']))
        return task_json(conn.execute('SELECT * FROM planner_tasks WHERE id=?',(str(task_id),)).fetchone())


@router.delete('/planner/checklist/{task_id}')
def delete_task(task_id:UUID,account=Depends(authenticated)):
    with connect() as conn:
        if not conn.execute('DELETE FROM planner_tasks WHERE id=? AND account_id=?',(str(task_id),account['id'])).rowcount:
            raise HTTPException(404,'Không tìm thấy công việc.')
    return {'deleted':True}


def ics_escape(value):
    return value.replace('\\','\\\\').replace('\r\n','\n').replace('\r','\n').replace('\n',r'\n').replace(';',r'\;').replace(',',r'\,')


def fold_ics(line):
    # RFC 5545: fold by UTF-8 OCTETS, never split a Unicode code point.
    parts,chunk = [],''
    for char in line:
        if len((chunk+char).encode())>75:
            parts.append(chunk)
            chunk=' '
        chunk+=char
    return '\r\n'.join([*parts,chunk])


@router.get('/planner/calendar')
def calendar(year:Year=2026,account=Depends(authenticated)):
    with connect() as conn:
        tasks = conn.execute('SELECT * FROM planner_tasks WHERE account_id=? AND admission_year=? AND due_date IS NOT NULL AND completed=0 ORDER BY due_date,id',(account['id'],year)).fetchall()
    lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//UTC Planner//VI','CALSCALE:GREGORIAN']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for task in tasks:
        day = date.fromisoformat(task['due_date'])
        lines += ['BEGIN:VEVENT',f"UID:{task['id']}@utc-planner",f'DTSTAMP:{stamp}',f'DTSTART;VALUE=DATE:{day:%Y%m%d}',f'DTEND;VALUE=DATE:{day+timedelta(days=1):%Y%m%d}',
                  'SUMMARY:'+ics_escape(task['title']),'DESCRIPTION:'+ics_escape(task['description'])]
        if task['source_url']:
            lines += ['URL:'+ics_escape(task['source_url'])]
        lines += ['END:VEVENT']
    lines += ['END:VCALENDAR']
    return {'filename':f'ke-hoach-tuyen-sinh-{year}.ics','content':'\r\n'.join(fold_ics(line) for line in lines)+'\r\n','events':len(tasks)}
