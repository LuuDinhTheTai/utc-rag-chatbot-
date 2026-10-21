"""Rotate the local administrator password and revoke all admin sessions."""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.localdb import connect
from app.security import password_hash

email = input('Admin email: ').strip().lower()
password = getpass.getpass('New password (at least 16 characters): ')
confirmation = getpass.getpass('Confirm new password: ')
if len(password) < 16 or password != confirmation:
    raise SystemExit('Password too short or confirmation does not match.')
with connect() as conn:
    row = conn.execute("SELECT id FROM accounts WHERE role='admin' AND email=?", (email,)).fetchone()
    if not row:
        raise SystemExit('Admin account not found.')
    conn.execute('UPDATE accounts SET password_hash=? WHERE id=?',
                 (password_hash(password), row['id']))
    conn.execute('DELETE FROM auth_sessions WHERE account_id=?', (row['id'],))
print('Password changed; existing sessions revoked.')
