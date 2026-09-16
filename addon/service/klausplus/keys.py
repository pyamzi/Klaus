"""Licence keys: minted once, stored only as a SHA-256 hash."""
from __future__ import annotations

import hashlib
import secrets

PREFIX = "kp_"
_HEX = set("0123456789abcdef")


def mint() -> str:
    return PREFIX + secrets.token_hex(16)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def looks_like_key(s: str) -> bool:
    return isinstance(s, str) and s.startswith(PREFIX) and len(s) == 35 and set(s[3:]) <= _HEX
