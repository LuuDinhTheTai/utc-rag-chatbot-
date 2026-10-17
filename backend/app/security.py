"""Password hashing for local administrator accounts."""
import hashlib
import hmac
import secrets


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ':' + digest.hex()


def check_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split(':', 1)
        return hmac.compare_digest(password_hash(password, bytes.fromhex(salt)).split(':', 1)[1], expected)
    except (ValueError, TypeError):
        return False