"""Create three demo accounts without overwriting existing users or passwords."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.localdb import connect, now
from app.security import password_hash


def seed():
    directory = Path(settings().data_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    database = directory / 'utc.sqlite3'
    backup = directory / 'utc.before-auth-v1.sqlite3.bak'
    if database.exists() and not backup.exists():
        with sqlite3.connect(database) as source, sqlite3.connect(backup) as target:
            source.backup(target)
    credentials_path = directory / 'auth-demo-credentials.local.json'
    credentials = json.loads(credentials_path.read_text(encoding='utf-8')) if credentials_path.exists() else []
    created = []
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for role, name in [('student', 'Sinh viên mẫu'), ('lecturer', 'Giảng viên mẫu'), ('admin', 'Admin mẫu')]:
            email = f'{role}.demo@utc.local'
            if conn.execute('SELECT id FROM accounts WHERE email=?', (email,)).fetchone():
                continue
            password = secrets.token_urlsafe(24)
            conn.execute('INSERT INTO accounts(id,email,display_name,password_hash,role,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                         (str(uuid4()), email, name, password_hash(password), role, now(), now()))
            created.append({'email': email, 'password': password, 'role': role})
        if created:
            # Keep credentials outside source control; never print passwords to logs.
            fd = os.open(credentials_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(credentials + created, handle, ensure_ascii=False, indent=2)
    return created, credentials_path


if __name__ == '__main__':
    created, path = seed()
    print(f'Created {len(created)} demo accounts. Existing accounts unchanged.')
    print('Credentials file: ' + str(path))
