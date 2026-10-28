"""Two-factor authentication (TOTP) helpers.

Secrets are encrypted at rest with the shared Fernet key and backup codes are
stored as salted hashes, never in plaintext.
"""
from __future__ import annotations

import base64
import io
import json
import secrets

import pyotp
import qrcode
from django.contrib.auth.hashers import check_password, make_password

from apps.integrations.crypto import decrypt, encrypt

ISSUER = "NexaMind"
BACKUP_CODE_COUNT = 10


def generate_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(secret: str) -> str:
    return encrypt(secret)


def _decrypt_secret(token: str) -> str:
    return decrypt(token or "")


def provisioning_uri(profile, secret: str | None = None) -> str:
    secret = secret or _decrypt_secret(profile.totp_secret)
    label = profile.user.email
    return pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name=ISSUER)


def qr_data_uri(uri: str) -> str:
    """Return a base64 PNG data URI for the otpauth URI."""
    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"


def _load_backup_codes(profile) -> list[str]:
    try:
        data = json.loads(profile.totp_backup_codes or "[]")
        return list(data) if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def generate_backup_codes(profile) -> list[str]:
    """Create fresh one-time backup codes and store their hashes."""
    plaintext = [secrets.token_hex(5) for _ in range(BACKUP_CODE_COUNT)]
    profile.totp_backup_codes = json.dumps([make_password(c) for c in plaintext])
    profile.save(update_fields=["totp_backup_codes", "updated_at"])
    return plaintext


def verify_totp(profile, code: str) -> bool:
    secret = _decrypt_secret(profile.totp_secret)
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


def verify_backup_code(profile, code: str) -> bool:
    code = (code or "").strip()
    if not code:
        return False
    hashes = _load_backup_codes(profile)
    for idx, hashed in enumerate(hashes):
        if check_password(code, hashed):
            del hashes[idx]
            profile.totp_backup_codes = json.dumps(hashes)
            profile.save(update_fields=["totp_backup_codes", "updated_at"])
            return True
    return False


def verify_any(profile, code: str) -> bool:
    return verify_totp(profile, code) or verify_backup_code(profile, code)
