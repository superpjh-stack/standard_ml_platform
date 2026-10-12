"""F20-3 · DEF-QAR2-003 — DB 를 지우는 make 대상은 **명령줄** `CONFIRM=1` 만 받는다(셸에 export 된 CONFIRM 은 거부).

QA-R2 재현: `export CONFIRM=1` 이 남은 셸에서 `make db-reset` 이 바로 돌았다(가짜 바이너리로 확인).
시험도 가짜 `psql` · `uv` · `npm` 을 PATH 앞에 두고 부른다 — 진짜 DB 에는 아무것도 하지 않는다(호출 기록만 본다).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("db-reset", "db-schema", "gate-full")


@pytest.fixture()
def fake_bin(tmp_path):
    log = tmp_path / "calls.log"
    b = tmp_path / "bin"
    b.mkdir()
    for name in ("psql", "uv", "npm", "createdb"):
        f = b / name
        f.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\nexit 0\n', encoding="utf-8")
        f.chmod(0o755)
    return {"bin": b, "log": log}


def make(fake_bin, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("CONFIRM", "MAKEFLAGS", "MFLAGS")}
    env["PATH"] = f"{fake_bin['bin']}{os.pathsep}{env['PATH']}"
    env.update(env_extra or {})
    return subprocess.run(["make", "-s", "-C", str(ROOT), *args], capture_output=True, text=True, env=env, timeout=60)


def calls(fake_bin) -> list[str]:
    return fake_bin["log"].read_text(encoding="utf-8").splitlines() if fake_bin["log"].exists() else []


@pytest.mark.parametrize("target", TARGETS)
def test_exported_confirm_is_refused(fake_bin, target):
    r = make(fake_bin, target, env_extra={"CONFIRM": "1"})
    assert r.returncode == 2 and calls(fake_bin) == [], (r.stdout, r.stderr)
    assert "명령줄" in (r.stdout + r.stderr)


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("value", ["", "0", "yes", "true", "01", "1 1"])
def test_wrong_cmdline_values_refused(fake_bin, target, value):
    r = make(fake_bin, target, f"CONFIRM={value}")
    assert r.returncode == 2 and calls(fake_bin) == []


def test_env_override_flag_is_refused(fake_bin):
    r = make(fake_bin, "-e", "db-reset", env_extra={"CONFIRM": "1"})
    assert r.returncode == 2 and calls(fake_bin) == []


def test_cmdline_confirm_runs_with_fake_binaries(fake_bin):
    r = make(fake_bin, "db-reset", "CONFIRM=1")
    assert r.returncode == 0, r.stderr
    got = calls(fake_bin)
    assert any(c.startswith("psql") and "schema.sql" in c for c in got)          # 재생성 경로까지 갔다(가짜 psql)
    assert any(c.startswith("uv run python -m mlcore.db.seed_std") for c in got)


def test_non_destructive_targets_need_no_confirm(fake_bin):
    r = make(fake_bin, "db-migrate", env_extra={"CONFIRM": "1"})
    assert r.returncode == 0 and any(c.startswith("psql") for c in calls(fake_bin))
