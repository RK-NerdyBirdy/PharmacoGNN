from __future__ import annotations

import base64
import datetime as dt
import os
from functools import lru_cache
from typing import Any

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from passlib.context import CryptContext

from app.core.config import settings

# --- Password hashing ---------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


# --- JWT session tokens ---------------------------------------------------

def create_access_token(subject: str, role: str, expires_delta: dt.timedelta | None = None) -> str:
    expire = dt.datetime.now(dt.timezone.utc) + (
        expires_delta or dt.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


# --- Field-level PHI encryption (AES-256-GCM, authenticated) ---------------
#
# Ciphertext layout stored in the DB column: base64( 12-byte nonce || GCM(ciphertext || 16-byte tag) ).
# GCM gives us confidentiality + integrity (a tampered ciphertext fails to decrypt) in one primitive,
# which is what the PHI columns (legal_name, date_of_birth, medical_record_number, emergency_contact)
# require. Note: because the nonce is random per encryption, ciphertext is non-deterministic — the
# same plaintext encrypted twice yields different bytes, so encrypted columns cannot be used in
# equality lookups, uniqueness constraints, or indexes. If exact-match search on an encrypted field
# is ever needed, add a separate deterministic blind-index column (e.g. HMAC-SHA256 of the normalized
# plaintext) rather than relying on the ciphertext itself.

_NONCE_SIZE = 12  # 96-bit nonce, standard for AES-GCM


@lru_cache
def _aesgcm() -> AESGCM:
    key = base64.urlsafe_b64decode(settings.FIELD_ENCRYPTION_KEY.encode("utf-8"))
    if len(key) != 32:
        raise ValueError("FIELD_ENCRYPTION_KEY must decode to exactly 32 bytes for AES-256-GCM")
    return AESGCM(key)


def encrypt_value(plaintext: str) -> str:
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = _aesgcm().encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_value(token: str) -> str:
    raw = base64.urlsafe_b64decode(token.encode("utf-8"))
    nonce, ciphertext = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
    plaintext = _aesgcm().decrypt(nonce, ciphertext, associated_data=None)
    return plaintext.decode("utf-8")
