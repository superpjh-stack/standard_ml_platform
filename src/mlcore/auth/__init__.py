"""API 키 인증 · 역할 (spec §17 · goal §6 · std/roles.yaml). 소유 개발2.

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

from ..serve.errors import ServeError
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


class Forbidden(ServeError):
    status, code, default_message = 403, "forbidden", "권한이 없습니다"


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


def require(principal: Principal | None, area: str, *, write: bool = True) -> Principal:
    """역할 판정(std/roles.yaml). 키가 없으면 AuthRequired, 역할 밖이면 Forbidden(403)."""
    if principal is None:
        raise AuthRequired()
    if not allowed(principal.role, area, write=write):
        raise Forbidden()
    return principal


def require_own_task(principal: Principal, area: str, approver_role: str) -> None:
    """own_task 규칙 — approver 는 자기 approver_role 과제만. admin 은 전부."""
    rule = permissions()[area].get(principal.role, "deny")
    if rule == "own_task" and approver_role not in principal.approver_roles:
        raise Forbidden("이 과제의 승인 담당이 아닙니다")
    if rule not in ("allow", "own_task"):
        raise Forbidden()


ROLE_RANK = {r: i for i, r in enumerate(ROLES)}


def at_least(principal: Principal, role: str) -> bool:
    return ROLE_RANK.get(principal.role, -1) >= ROLE_RANK[role]
