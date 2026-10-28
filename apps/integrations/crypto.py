"""Symmetric encryption for stored OAuth tokens.

The key is read from NEXAMIND['TOKEN_ENCRYPTION_KEY']. When it is absent the
key is derived from DJANGO_SECRET_KEY so that development works out of the box;
production deployments must set an explicit, externally managed key.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger("nexamind.integrations")


def _fernet():
    raw = settings.NEXAMIND.get("TOKEN_ENCRYPTION_KEY") or ""
    if not raw:
        logger.warning(
            "TOKEN_ENCRYPTION_KEY is not set; deriving a key from SECRET_KEY. "
            "Set an explicit key in production."
        )
        raw = settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def encrypt(value):
    if value is None:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token):
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt a stored credential (key mismatch?).")
        return ""
