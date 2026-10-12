"""API 키 인증 · 역할 (spec §17 · goal §6 · std/roles.yaml). Phase 0 골격 — 이후 소유 개발2.

- 키는 해시(`sha256$<hex>`)로만 저장한다. API 키는 32바이트 이상 무작위 값이라 무염 SHA-256 으로 조회한다.
- 키의 회사와 경로의 회사가 다르면 404 (존재 숨김). 역할 판정표는 std/roles.yaml 하나가 출처다.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from functools import lru_cache

import yaml

from ..settings import ROOT

ROLES = ("viewer", "operator", "approver", "admin")


@dataclass(frozen=True)
class Principal:
    key_id: int
    tenant_id: str
    role: str
    consumer: str
    approver_roles: tuple[str, ...] = ()


class AuthRequired(Exception):
    pass


class Forbidden(Exception):
    pass


def hash_key(raw: str) -> str:
    return "sha256$" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_key() -> tuple[str, str]:
    """(평문 키 — 한 번만 보여 준다, 저장할 해시)."""
    raw = "mlp_" + secrets.token_urlsafe(32)
    return raw, hash_key(raw)


def verify_hash(raw: str, stored: str) -> bool:
    return hmac.compare_digest(hash_key(raw), stored)


@lru_cache(maxsize=1)
def permissions() -> dict:
    return yaml.safe_load((ROOT / "std" / "roles.yaml").read_text(encoding="utf-8"))["permissions"]


def allowed(role: str, area: str, *, write: bool = True) -> bool:
    """area = std/roles.yaml permissions 키. write=False 면 'read' 도 허용."""
    rule = permissions()[area].get(role, "deny")
    if rule in ("allow", "own_task"):
        return True
    return rule == "read" and not write


def lookup(raw: str | None) -> Principal:
    """X-API-Key → Principal. 없거나 틀리면 AuthRequired."""
    if not raw:
        raise AuthRequired()
    from ..db.conn import q1
    row = q1("SELECT key_id, tenant_id, role, consumer, approver_roles FROM mlp_api_key "
             "WHERE key_hash = %s AND active AND revoked_at IS NULL", (hash_key(raw),))
    if not row:
        raise AuthRequired()
    return Principal(row["key_id"], row["tenant_id"], row["role"], row["consumer"], tuple(row["approver_roles"] or ()))
