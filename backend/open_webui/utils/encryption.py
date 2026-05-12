"""Shared encryption helpers.

Secrets are stored at rest behind a veil — what is written
is not what is read, until the right key turns the lock.
"""

import base64
import hashlib
import json

from cryptography.fernet import Fernet
from open_webui.env import OAUTH_SESSION_TOKEN_ENCRYPTION_KEY


def _fernet() -> Fernet:
    key = OAUTH_SESSION_TOKEN_ENCRYPTION_KEY
    if not key:
        raise Exception('OAUTH_SESSION_TOKEN_ENCRYPTION_KEY is not set')
    if len(key) != 44:
        key = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
    else:
        key = key.encode()
    return Fernet(key)


def encrypt_dict(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_dict(ciphertext: str) -> dict:
    return json.loads(_fernet().decrypt(ciphertext.encode()).decode())
