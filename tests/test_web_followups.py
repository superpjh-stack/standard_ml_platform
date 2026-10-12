"""1차 잔여 F16-9 · F19-3 회귀 시험 (docs/followups.md, 개발2) — 콘솔 소스 정적 검사.

- F16-9: 콘솔이 API 키를 localStorage(영구)에 두지 않는다 — 키는 sessionStorage, localStorage 에는 회사 코드만.
  예전 형식(localStorage 에 키까지)은 읽을 때 sessionStorage 로 옮기고 localStorage 에서 지운다.
- F19-3: web/vite.config 개발 프록시 포트가 8200 고정이 아니라 환경변수 MLP_API_PORT(기본 8200)를 읽는다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "web" / "src" / "components" / "api.ts").read_text(encoding="utf-8")
VITE = (ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")


def _set_connection_body() -> str:
    m = re.search(r"export function setConnection\(.*?\n\}", API, re.S)
    assert m, "setConnection 없음"
    return m.group(0)


def test_f16_9_key_in_session_storage_only():
    body = _set_connection_body()
    assert "sessionStorage.setItem(KEY_STORE, c.key)" in body
    assert re.findall(r"localStorage\.setItem\([^;]*\)", body) == ["localStorage.setItem(STORE, JSON.stringify({tenant: c.tenant}))"]
    assert "JSON.stringify({tenant: c.tenant})" in body
    # 어디에서도 localStorage 에 c.key 를 쓰지 않는다
    assert not re.search(r"localStorage\.setItem\([^)]*\bc\.key\b", API)
    # 예전 형식 이관 — 키를 세션으로 옮기고 영구 저장소를 회사 코드만으로 다시 쓴다
    assert "sessionStorage.setItem(KEY_STORE, String(c.key))" in API
    assert "localStorage.setItem(STORE, JSON.stringify({tenant}))" in API


def test_f16_9_no_other_screen_touches_local_storage_key():
    for p in (ROOT / "web" / "src").rglob("*.ts*"):
        if p.name == "api.ts":
            continue
        assert "localStorage" not in p.read_text(encoding="utf-8"), p


def test_f19_3_proxy_port_from_env():
    assert "process.env.MLP_API_PORT" in VITE
    assert "'http://127.0.0.1:8200'" not in VITE                  # 고정 문자열 아님
    assert "proxy: {'/api': `http://127.0.0.1:${apiPort}`}" in VITE
    assert "'8200'" in VITE                                         # 기본값 8200 (D-14)
