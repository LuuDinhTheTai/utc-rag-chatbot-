"""Local authentication and role-based account administration."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import settings
from .localdb import connect, now
from .security import check_password, password_hash

router = APIRouter(tags=['Authentication'])
PERMISSIONS = {
    'guest': {'catalogue:read', 'chat:use'},
    'student': {'catalogue:read', 'chat:use', 'account:self'},
    'lecturer': {'catalogue:read', 'chat:use', 'account:self', 'content:read', 'content:write'},
    'admin': {'catalogue:read', 'chat:use', 'account:self', 'content:read', 'content:write', 'accounts:manage'},
}

def bootstrap_admin():
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT id FROM accounts WHERE role='admin' LIMIT 1").fetchone():
            return
        cfg = settings()
        if not cfg.admin_email or not cfg.admin_password:
            raise HTTPException(503, 'Configure ADMIN_EMAIL and ADMIN_PASSWORD on the server.')
        if len(cfg.admin_password) < 16 or cfg.admin_password.startswith('CHANGE_ME'):
            raise HTTPException(503, 'Set a unique ADMIN_PASSWORD of at least 16 characters.')
        conn.execute("INSERT INTO accounts(id,email,password_hash,role,created_at,updated_at) VALUES(?,?,?,'admin',?,?)",
                     (str(uuid4()), cfg.admin_email.strip().lower(), password_hash(cfg.admin_password), now(), now()))



class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


@router.post('/admin/login')
@router.post('/auth/login')
def login(body: LoginInput):
    # Bootstrap only the configured administrator, never on arbitrary sign-in attempts.
    if body.email.strip().lower() == settings().admin_email.strip().lower():
        bootstrap_admin()
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM accounts WHERE email=?', (body.email.strip().lower(),)).fetchone()
        if not row or not row['is_active'] or not check_password(body.password, row['password_hash']):
            raise HTTPException(401, 'Invalid email or password.')
        token = secrets.token_urlsafe(32)
        expiry = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        conn.execute('DELETE FROM auth_sessions WHERE expires_at<=?', (now(),))
        conn.execute('INSERT INTO auth_sessions(token_hash,account_id,expires_at,created_at) VALUES(?,?,?,?)',
                     (hashlib.sha256(token.encode()).hexdigest(), row['id'], expiry, now()))
    return {'token': token, 'id': row['id'], 'role': row['role'], 'email': row['email'], 'display_name': row['display_name'], 'expires_at': expiry, 'permissions': sorted(PERMISSIONS[row['role']])}


@router.post('/admin/logout')
@router.post('/auth/logout')
def logout(authorization: str = Header(default='')):
    if authorization.startswith('Bearer '):
        with connect() as conn:
            conn.execute('DELETE FROM auth_sessions WHERE token_hash=?',
                         (hashlib.sha256(authorization[7:].encode()).hexdigest(),))
    return {'ok': True}


def optional_account(authorization: str = Header(default='')):
    if not authorization:
        return None
    if not authorization.startswith('Bearer ') or not 32 <= len(authorization[7:]) <= 200:
        raise HTTPException(401, 'Phiên đăng nhập không hợp lệ.')
    with connect() as conn:
        row = conn.execute('SELECT a.id,a.email,a.display_name,a.role FROM auth_sessions AS s JOIN accounts AS a ON a.id=s.account_id WHERE s.token_hash=? AND s.expires_at>? AND a.is_active=1',
                           (hashlib.sha256(authorization[7:].encode()).hexdigest(), datetime.now(timezone.utc).isoformat())).fetchone()
    if not row:
        raise HTTPException(401, 'Phiên đăng nhập hết hạn hoặc đã bị thu hồi. Vui lòng đăng nhập lại.')
    return dict(row)


def authenticated(account=Depends(optional_account)):
    if account is None:
        raise HTTPException(401, 'Vui lòng đăng nhập.')
    return account


def admin(account=Depends(authenticated)):
    if 'content:read' not in PERMISSIONS[account['role']]:
        raise HTTPException(403, 'Bạn không có quyền quản lý nội dung.')
    return account['id']


@router.get('/auth/me')
def me(account=Depends(optional_account)):
    user = account or {'id': None, 'email': None, 'display_name': 'Khách', 'role': 'guest'}
    return {**user, 'permissions': sorted(PERMISSIONS[user['role']])}


def require_permission(uid: str, permission: str):
    with connect() as conn:
        row = conn.execute('SELECT role FROM accounts WHERE id=? AND is_active=1', (uid,)).fetchone()
    if not row:
        raise HTTPException(401, 'Invalid or expired admin session.')
    if permission not in PERMISSIONS[row['role']]:
        raise HTTPException(403, 'Bạn không có quyền thực hiện thao tác này.')
    return uid


def can_edit(uid: str = Depends(admin)):
    return require_permission(uid, 'content:write')


def owner(uid: str = Depends(admin)):
    return require_permission(uid, 'accounts:manage')


@router.get('/admin/me')
def current_admin(uid: str = Depends(admin)):
    with connect() as conn:
        row = conn.execute('SELECT id,email,role FROM accounts WHERE id=?', (uid,)).fetchone()
    return dict(row)


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(default='', max_length=100)
    password: str = Field(min_length=16, max_length=256)
    role: Literal['admin', 'lecturer', 'student']


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['admin', 'lecturer', 'student'] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=16, max_length=256)


@router.get('/admin/accounts')
def list_accounts(uid: str = Depends(owner)):
    with connect() as conn:
        return [dict(row) for row in conn.execute(
            'SELECT id,email,display_name,role,is_active,created_at FROM accounts ORDER BY email'
        )]


@router.post('/admin/accounts', status_code=201)
def create_account(body: AccountCreate, uid: str = Depends(owner)):
    import re
    email = body.email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise HTTPException(422, 'Email không hợp lệ.')
    import sqlite3
    account_id = str(uuid4())
    try:
        with connect() as conn:
            conn.execute('INSERT INTO accounts(id,email,display_name,password_hash,role,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                         (account_id, email, body.display_name.strip(), password_hash(body.password), body.role, now(), now()))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, 'Email đã tồn tại.') from exc
    return {'id': account_id, 'email': email, 'role': body.role, 'is_active': True}


@router.patch('/admin/accounts/{account_id}')
def update_account(account_id: UUID, body: AccountUpdate, uid: str = Depends(owner)):
    changes = body.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422, 'Cần cung cấp giá trị cập nhật hợp lệ.')
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT id,role,is_active FROM accounts WHERE id=?', (str(account_id),)).fetchone()
        if not row:
            raise HTTPException(404, 'Không tìm thấy tài khoản.')
        if str(account_id) == uid and (changes.get('role', 'admin') != 'admin' or changes.get('is_active') is False):
            raise HTTPException(409, 'Không thể tự hạ quyền hoặc khóa tài khoản.')
        new_role = changes.get('role', row['role'])
        new_active = changes.get('is_active', bool(row['is_active']))
        if row['role'] == 'admin' and row['is_active'] and (new_role != 'admin' or not new_active):
            count = conn.execute("SELECT COUNT(*) FROM accounts WHERE role='admin' AND is_active=1").fetchone()[0]
            if count <= 1:
                raise HTTPException(409, 'Phải giữ ít nhất một quản trị viên đang hoạt động.')
        if 'password' in changes:
            changes['password_hash'] = password_hash(changes.pop('password'))
        if 'is_active' in changes:
            changes['is_active'] = int(changes['is_active'])
        changes['updated_at'] = now()
        fields = ','.join(f'{name}=?' for name in changes)
        conn.execute(f'UPDATE accounts SET {fields} WHERE id=?', (*changes.values(), str(account_id)))
        if 'password_hash' in changes or 'role' in changes or not new_active:
            conn.execute('DELETE FROM auth_sessions WHERE account_id=?', (str(account_id),))
        result = conn.execute('SELECT id,email,role,is_active FROM accounts WHERE id=?', (str(account_id),)).fetchone()
    return dict(result)


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=16, max_length=256)

    @field_validator('display_name')
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError('Họ tên cần ít nhất 2 ký tự.')
        return value


@router.post('/auth/register', status_code=201)
def register(body: RegisterInput):
    # Roles cannot be supplied by self-registration.
    if body.email.strip().lower() == settings().admin_email.strip().lower():
        raise HTTPException(409, 'Email đã được dành cho tài khoản quản trị.')
    return create_account(AccountCreate(**body.model_dump(), role='student'), uid=None)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=16, max_length=256)


@router.post('/auth/password')
def change_password(body: PasswordChange, account=Depends(authenticated)):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT password_hash FROM accounts WHERE id=?', (account['id'],)).fetchone()
        if not row or not check_password(body.current_password, row['password_hash']):
            raise HTTPException(400, 'Mật khẩu hiện tại không đúng.')
        conn.execute('UPDATE accounts SET password_hash=?,updated_at=? WHERE id=?',
                     (password_hash(body.new_password), now(), account['id']))
        conn.execute('DELETE FROM auth_sessions WHERE account_id=?', (account['id'],))
    return {'ok': True}

