"""QA3 공용 — 실제 uvicorn(포트 8204)에 HTTP 요청. 키 평문은 scratchpad keys.json 에서만 읽는다."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

BASE = os.environ.get("QAR2_BASE", "http://127.0.0.1:8204")
KEYS_PATH = os.environ.get("QAR2_KEYS")
KEYS = json.load(open(KEYS_PATH)) if KEYS_PATH else {}
ROWS: list[str] = []
FAILS: list[str] = []


def h(tenant: str, role: str) -> dict:
    return {"X-API-Key": KEYS[tenant][role]}


def call(method: str, path: str, *, tenant=os.environ.get("QAR2_TENANT", "ks"), role="admin", json_body=None, content=None, headers=None):
    hd = {} if role is None else h(tenant, role)
    hd.update(headers or {})
    if content is not None:
        hd["Content-Type"] = "application/json"
    r = httpx.request(method, BASE + path, json=json_body, content=content, headers=hd, timeout=60)
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = r.text
    return r.status_code, body


def code_of(body) -> str | None:
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return body["error"].get("code")
    return None


def check(gid: str, item: str, ok: bool, measured: str, warn: bool = False):
    verdict = "PASS" if ok else ("WARN" if warn else "FAIL")
    row = f"{gid}  {item}  {verdict}  {measured}"
    ROWS.append(row)
    if not ok:
        FAILS.append(row)
    print(row, flush=True)
    return ok


def expect(gid, item, st, body, want_status, want_code=None, extra_ok=True, extra=""):
    got_code = code_of(body)
    ok = st == want_status and (want_code is None or got_code == want_code) and extra_ok
    return check(gid, item, ok, f"HTTP {st} code={got_code} (기대 {want_status} {want_code or ''}) {extra}".strip())


def dump(path: str):
    Path(path).write_text("\n".join(ROWS) + "\n", encoding="utf-8")
