from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import PHOTO_ENCRYPTION_KEY

_PHOTO_MAGIC = b"FACEMEENC1"
_NONCE_SIZE = 12
_AAD = b"faceme-photo"


def _build_cipher() -> AESGCM:
    key = hashlib.sha256(PHOTO_ENCRYPTION_KEY.encode("utf-8")).digest()
    return AESGCM(key)


_CIPHER = _build_cipher()


def encrypt_photo_bytes(data: bytes) -> bytes:
    nonce = os.urandom(_NONCE_SIZE)
    encrypted = _CIPHER.encrypt(nonce, data, _AAD)
    return _PHOTO_MAGIC + nonce + encrypted


def decrypt_photo_bytes(data: bytes) -> bytes:
    if not data.startswith(_PHOTO_MAGIC):
        return data
    nonce = data[len(_PHOTO_MAGIC):len(_PHOTO_MAGIC) + _NONCE_SIZE]
    ciphertext = data[len(_PHOTO_MAGIC) + _NONCE_SIZE:]
    if len(nonce) != _NONCE_SIZE or not ciphertext:
        raise ValueError("Encrypted photo payload is invalid")
    return _CIPHER.decrypt(nonce, ciphertext, _AAD)
