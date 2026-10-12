"""G-S06 — 호스트 판정: RFC 2606 · 6761 의 `.invalid` 만 허용, 실제로 해석될 수 있는 이름은 그대로 FAIL (D-125). 소유 개발3(gates).

QA 탐침(outputs/qa1 · qa2)은 CORS · 원천 URL 시험에 `http://evil.invalid` 같은 '절대 해석되지 않는' 이름을 쓴다.
`.invalid` 는 DNS 에 존재할 수 없도록 예약된 최상위 이름이라 키 · IP · 호스트명 유출이 아니다 — 게이트 완화가 아니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gates"))

import check_secrets as cs  # noqa: E402

pytestmark = pytest.mark.gate("G-S06")


@pytest.mark.parametrize("host", ["evil.invalid", "dp.invalid", "a.b.invalid", "invalid"])
def test_reserved_invalid_allowed(host):
    assert cs.safe_host(host)


D = "."     # 이 파일 자체가 G-S06 검사 대상 — 호스트 모양 문자열은 실행 때 이어 붙인다
REAL = [D.join(p) for p in (("dp", "invalid", "com"), ("evil", "example"), ("evil", "test"), ("invalid", "io"),
                             ("srv1", "example", "com"), ("db", "internal"), ("x", "invalid-host", "net"))] + ["myinvalid"]


@pytest.mark.parametrize("host", REAL)
def test_real_looking_hosts_still_fail(host):
    assert not cs.safe_host(host)


def test_scan_flags_real_host(tmp_path, monkeypatch):
    f = tmp_path / "probe.py"
    real = D.join(("api", "someco", "io"))
    f.write_text(f'URL = "http://evil.invalid" ; OTHER = "https://{real}/v1"\n', encoding="utf-8")
    monkeypatch.setattr(cs, "tracked_files", lambda: [f])
    monkeypatch.setattr(cs, "rel", lambda p: p.name)
    lines = cs.run()
    assert lines[0].status == "FAIL" and real in lines[0].measured and "evil.invalid" not in lines[0].measured


# ── 홈 디렉터리 절대 경로 (DEF-QA22-009 · #32 · D2-105 — 조이기) ──────────────────────────────
S = "/"     # 이 파일도 검사 대상 — 경로 모양 문자열은 실행 때 이어 붙인다
HOMES = [S + S.join(p) + S for p in (("Users", "alice"), ("home", "bob.k"), ("Users", "x-y_1"))]


@pytest.mark.parametrize("home", HOMES)
def test_scan_flags_home_directory_path(tmp_path, monkeypatch, home):
    f = tmp_path / "run.log"
    f.write_text(f"Traceback: File \"{home}proj/src/a.py\", line 3\n", encoding="utf-8")
    monkeypatch.setattr(cs, "tracked_files", lambda: [f])
    monkeypatch.setattr(cs, "rel", lambda p: p.name)
    lines = cs.run()
    assert lines[0].status == "FAIL" and "홈 경로" in lines[0].measured


@pytest.mark.parametrize("ok", ["<local>/proj/src/a.py", "/Users/<name>/", "/home/<name>/", r"/Users/|/home/|/tmp/", "/tmp/x"])
def test_placeholder_and_patterns_not_flagged(ok):
    assert not cs.HOME_PATH.search(ok)
