"""签名、ID 生成等小工具。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from .config import settings

# 去掉易混淆字符（0/O、1/I/L）
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_id(prefix: str, nbytes: int = 10) -> str:
    return f"{prefix}{secrets.token_hex(nbytes)}"


def new_pickup_code(length: int = 8) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def sign(value: str, length: int = 22) -> str:
    digest = hmac.new(settings.secret_key.encode(), value.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:length]


def verify(value: str, signature: str, length: int = 22) -> bool:
    return hmac.compare_digest(sign(value, length), signature or "")


def signed_query(path_key: str, ttl_seconds: int) -> str:
    """生成带有效期的签名查询串：exp=...&sig=..."""
    exp = int(time.time()) + ttl_seconds
    return f"exp={exp}&sig={sign(f'{path_key}|{exp}')}"


def check_signed(path_key: str, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    return verify(f"{path_key}|{exp}", sig)
