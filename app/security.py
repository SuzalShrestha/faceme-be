from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import PHOTO_ENCRYPTION_KEY

_PREFIX = b"FEME1"


def _derive_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


_cipher = Fernet(_derive_key(PHOTO_ENCRYPTION_KEY))


def encrypt_bytes(data: bytes) -> bytes:
    if data.startswith(_PREFIX):
        return data
    return _PREFIX + _cipher.encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    if data.startswith(_PREFIX):
        token = data[len(_PREFIX) :]
        try:
            return _cipher.decrypt(token)
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt photo data") from exc
    return data


def is_encrypted(data: bytes) -> bool:
    return data.startswith(_PREFIX)
