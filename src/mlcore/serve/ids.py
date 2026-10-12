"""ID 생성 — `<접두>_<ULID>` (contracts/db-schema.md: prd_ · apr_ · rec_ · run_)."""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # Crockford base32


def ulid() -> str:
    """시각(ms, 48비트) + 무작위 80비트 → 26자. 시간순 정렬된다."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    out = []
    for _ in range(26):
        value, r = divmod(value, 32)
        out.append(_ALPHABET[r])
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    return f"{prefix}_{ulid()}"
