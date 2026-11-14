"""Generate API key and secret for Career API access."""
import argparse
import hashlib
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.localdb import connect, now
from app.security import password_hash


def parse_datetime_utc(date_str: str) -> datetime:
    """
    Parse datetime string and ensure UTC timezone.

    Accepts:
        - ISO 8601 with timezone: "2024-12-31T23:59:59+00:00"
        - ISO 8601 without timezone (assumes UTC): "2024-12-31T23:59:59"
        - Date only (assumes end of day UTC): "2024-12-31"

    Returns:
        datetime with UTC timezone

    Raises:
        ValueError: If format is invalid or date is in the past
    """
    try:
        # Try parsing with timezone
        dt = datetime.fromisoformat(date_str)

        # If no timezone, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            # Convert to UTC
            dt = dt.astimezone(timezone.utc)

        return dt

    except ValueError:
        # Try date-only format
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            # End of day UTC
            dt = dt.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            return dt
        except ValueError:
            raise ValueError(f'Invalid date format: {date_str}. Use ISO 8601 or YYYY-MM-DD')


def generate_api_credentials(
    name: str,
    permissions: list[str],
    created_by: str | None = None,
    expires_at: str | None = None,
    description: str = ''
) -> tuple[str, str, str]:
    """
    Generate API key and secret pair.

    Args:
        name: Human-readable name for the API key
        permissions: List of permissions (e.g., ["career:ingest"])
        created_by: Account ID of creator (optional)
        expires_at: Expiry datetime string (optional)
        description: Optional description

    Returns:
        (api_key, api_secret, key_id)
        - api_key: 32-byte URL-safe token (public, can be logged)
        - api_secret: 48-byte URL-safe token (private, NEVER log)
        - key_id: UUID of created record

    Security:
        - api_key stored as SHA-256 hash
        - api_secret stored as scrypt hash
        - Both required for authentication
    """

    # Generate credentials
    api_key = secrets.token_urlsafe(32)      # ~43 chars
    api_secret = secrets.token_urlsafe(48)   # ~64 chars

    # Hash for storage
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    secret_hash = password_hash(api_secret)

    # Validate and normalize expiry
    expiry_utc_str = None
    if expires_at:
        expiry_utc = parse_datetime_utc(expires_at)

        # Check not in past
        now_utc = datetime.now(timezone.utc)
        if expiry_utc <= now_utc:
            raise ValueError('Expiry must be in the future')

        expiry_utc_str = expiry_utc.isoformat()

    # Store in database
    key_id = str(uuid4())
    timestamp = now()

    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            conn.execute('''
                INSERT INTO api_keys (
                    id, key_hash, secret_hash, name, description, permissions,
                    is_active, created_at, created_by, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            ''', (
                key_id,
                key_hash,
                secret_hash,
                name,
                description,
                json.dumps(permissions),
                timestamp,
                created_by,
                expiry_utc_str
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return (api_key, api_secret, key_id)


def main():
    parser = argparse.ArgumentParser(
        description='Generate API key and secret for Career API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Basic key for TopCV crawler
  python generate_api_key.py --name "TopCV Crawler" --permissions career:ingest

  # Key with expiry
  python generate_api_key.py --name "Test Key" --permissions career:ingest --expires 2024-12-31

  # Key with description and creator
  python generate_api_key.py \\
    --name "Production Crawler" \\
    --permissions career:ingest \\
    --description "Main production crawler for job data" \\
    --created-by <admin-account-id> \\
    --expires 2025-12-31

Security:
  - API_SECRET is displayed ONCE and never stored in plain text
  - Save credentials in a secure location (e.g., password manager, .env file)
  - Do NOT commit credentials to git
  - Use different keys for development/staging/production
        '''
    )

    parser.add_argument(
        '--name',
        required=True,
        help='Human-readable name for the API key (e.g., "TopCV Crawler")'
    )

    parser.add_argument(
        '--permissions',
        nargs='+',
        required=True,
        help='Space-separated list of permissions (e.g., career:ingest)'
    )

    parser.add_argument(
        '--description',
        default='',
        help='Optional description'
    )

    parser.add_argument(
        '--created-by',
        help='Account ID of creator (optional)'
    )

    parser.add_argument(
        '--expires',
        help='Expiry date (ISO 8601 or YYYY-MM-DD, optional)'
    )

    parser.add_argument(
        '--output',
        choices=['env', 'json', 'text'],
        default='text',
        help='Output format (default: text)'
    )

    args = parser.parse_args()

    try:
        api_key, api_secret, key_id = generate_api_credentials(
            name=args.name,
            permissions=args.permissions,
            created_by=args.created_by,
            expires_at=args.expires,
            description=args.description
        )

        if args.output == 'env':
            # .env file format
            print('# Add these to your .env file:')
            print(f'CAREER_API_KEY={api_key}')
            print(f'CAREER_API_SECRET={api_secret}')
            print()
            print(f'# Key ID: {key_id}')
            print(f'# Name: {args.name}')
            print(f'# Permissions: {", ".join(args.permissions)}')
            if args.expires:
                print(f'# Expires: {args.expires}')

        elif args.output == 'json':
            # JSON format (for automation)
            output = {
                'key_id': key_id,
                'api_key': api_key,
                'api_secret': api_secret,
                'name': args.name,
                'permissions': args.permissions,
                'expires_at': args.expires
            }
            print(json.dumps(output, indent=2))

        else:
            # Human-readable text (default)
            print()
            print('=' * 70)
            print('API Credentials Generated Successfully')
            print('=' * 70)
            print()
            print(f'Key ID:        {key_id}')
            print(f'Name:          {args.name}')
            print(f'Permissions:   {", ".join(args.permissions)}')
            if args.expires:
                print(f'Expires:       {args.expires}')
            print()
            print('API Key (public, can be logged):')
            print(f'  {api_key}')
            print()
            print('API Secret (PRIVATE, never log):')
            print(f'  {api_secret}')
            print()
            print('=' * 70)
            print('⚠️  SECURITY WARNING')
            print('=' * 70)
            print('- API Secret is displayed ONCE and cannot be recovered')
            print('- Store credentials in a secure location immediately')
            print('- Do NOT commit credentials to git')
            print('- Use environment variables in production')
            print()
            print('Configuration example:')
            print('  CAREER_API_KEY=' + api_key)
            print('  CAREER_API_SECRET=' + api_secret)
            print()

        sys.exit(0)

    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f'Unexpected error: {exc}', file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
