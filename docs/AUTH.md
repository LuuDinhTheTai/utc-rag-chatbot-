# Authentication and RBAC

The website has four roles: guest, student, lecturer and admin. Guests are anonymous visitors and do not require an account row. Three authenticated roles are enforced by a SQLite CHECK constraint in `accounts`.

| Permission | Guest | Student | Lecturer | Admin |
| --- | --- | --- | --- | --- |
| Public catalogue, cutoffs, freshman guides, chat | Yes | Yes | Yes | Yes |
| Own account and password | — | Yes | Yes | Yes |
| Read/write recruitment content, review feedback | No | No | Yes | Yes |
| Create users, assign roles, lock/unlock, reset passwords | No | No | No | Yes |

## API

- `POST /auth/register`: email, display_name, password. Always creates a student; role and extra fields are rejected. This is self-registration, not proof of university enrolment.
- `POST /auth/login`: email, password. Returns a 12-hour opaque Bearer token and the account's permissions.
- `GET /auth/me`: current account; no token returns the guest role, invalid tokens return 401.
- `POST /auth/logout`: revokes the presented session.
- `POST /auth/password`: current_password, new_password; revokes all sessions on success.
- `/admin/accounts`: admin-only listing and creation; `PATCH /admin/accounts/{id}` updates role/status/password.
- `/admin/login` and `/admin/logout` remain compatibility aliases; `/admin/me` requires lecturer/admin.

Passwords use salted scrypt; only token SHA-256 hashes are persisted. New passwords require 16–256 characters. Login, registration and password changes share the auth rate-limit bucket. Public signup cannot choose a privileged role or use the configured bootstrap admin email. Backend checks account activity and token expiry for every authenticated request. Role/status/password changes revoke all sessions; frontend hides controls for unavailable permissions but is not the security boundary.

The web app uses one AuthProvider and stores the Bearer token in sessionStorage under `utc-auth-token`. Authenticated API calls automatically attach it. Logout, expiry and account changes clear the browser's current chat token and visible conversation. The application never persists account passwords in browser storage.

## Database and migration

`accounts`: id, normalized case-insensitive unique email, display_name, password_hash, role, is_active, created_at, updated_at.

`auth_sessions`: token_hash, account_id (foreign key), expires_at, created_at.

`chat_sessions.account_id`: nullable foreign key to accounts; NULL means an anonymous chat. Account-bound chat requires both the matching account and the chat token. Anonymous sessions retain their existing token ownership model.

`schema_migrations`: records `accounts_v1` under a write transaction. Existing admins are copied once with unchanged IDs, password hashes and active status; editor becomes lecturer, viewer becomes student. Legacy admin tables are retained for reference and old auth sessions are invalidated by switching auth stores. Unrelated legacy `users` tables and recruitment data are not deleted. Future account changes only affect `accounts`.

The bootstrap admin is created only when signing in using the configured ADMIN_EMAIL and no admin row exists. Creating a student first does not prevent admin bootstrap. The password rotation CLI now operates on accounts/auth_sessions.

## Three demo rows

Run `python scripts/seed_auth.py` from backend. It adds one student, one lecturer, one admin with independently generated passwords; existing accounts are never overwritten. Credentials are written to DATA_DIR/auth-demo-credentials.local.json, ignored by git. Existing databases are backed up using SQLite's backup API before migration. Re-running is idempotent. The three sample emails end in `@utc.local` and are local demo identities, not university email accounts.

## Verification

Tests cover registration escalation attempts, case-insensitive duplicates, password hashing, token expiry, logout, password-change revocation, blocked users, role changes, lecturer content CRUD, admin account management, cross-account chat isolation, one-time migration and idempotent sample data.
