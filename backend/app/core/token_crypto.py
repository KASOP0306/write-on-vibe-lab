"""서버 측 민감 토큰(GitHub PAT 등) 인증 암호화 및 마스킹 유틸리티."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from app.config import settings

_PREFIX = "enc1:"


def _derive_keys() -> tuple[bytes, bytes]:
    seed = (settings.app_secret_key or settings.database_url or "write-on-vibe-lab-local-key").encode("utf-8")
    enc_key = hashlib.sha256(seed + b"::github_token_enc_v1").digest()
    mac_key = hashlib.sha256(seed + b"::github_token_mac_v1").digest()
    return enc_key, mac_key


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(enc_key + nonce + counter.to_bytes(4, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt_secret(plaintext: str) -> str:
    """인증 암호화(SHA256-CTR + HMAC-SHA256)로 토큰을 암호화해 DB 저장용 문자열을 반환한다."""
    clean = (plaintext or "").strip()
    if not clean:
        return ""
    enc_key, mac_key = _derive_keys()
    nonce = secrets.token_bytes(16)
    raw = clean.encode("utf-8")
    stream = _keystream(enc_key, nonce, len(raw))
    ciphertext = bytes(a ^ b for a, b in zip(raw, stream))
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    blob = base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")
    return f"{_PREFIX}{blob}"


def decrypt_secret(encrypted: str) -> str:
    """암호화된 토큰 문자열을 무결성 검증 후 복호화한다. 위변조·손상 시 빈 문자열을 반환한다."""
    raw_str = (encrypted or "").strip()
    if not raw_str or not raw_str.startswith(_PREFIX):
        return ""
    try:
        blob = base64.urlsafe_b64decode(raw_str[len(_PREFIX):].encode("ascii"))
        if len(blob) < 48:
            return ""
        nonce = blob[:16]
        tag = blob[16:48]
        ciphertext = blob[48:]
        enc_key, mac_key = _derive_keys()
        expected_tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            return ""
        stream = _keystream(enc_key, nonce, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
        return plaintext.decode("utf-8").strip()
    except Exception:
        return ""


def mask_token(token: str) -> str:
    """UI 표시용 마스킹 문자열(예: ghp_****1234)을 반환한다."""
    clean = (token or "").strip()
    if not clean:
        return ""
    if len(clean) <= 8:
        return "*" * len(clean)
    return f"{clean[:4]}****{clean[-4:]}"
