"""F7-5 (#7) — `make image` 는 커밋한 작업 트리에서만 빌드한다(태그 = 커밋 SHA). bench 측정 이미지는 미커밋 트리면
`<sha>-wt<해시>` 태그를 쓴다 — 미커밋 트리로 빌드한 이미지에 커밋 SHA 를 붙이지 않는다.

가짜 `git` · `docker` 를 PATH 앞에 둔다 — 진짜 이미지를 만들지 않는다(호출 기록만 본다).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def fake(tmp_path):
    log, b = tmp_path / "calls.log", tmp_path / "bin"
    b.mkdir()
    (b / "git").write_text(f'#!/bin/sh\necho "git $*" >> "{log}"\ncase "$1" in\n  status) printf "%s" "$FAKE_STATUS";;\n'
                           f'  rev-parse) echo abc1234;;\nesac\nexit 0\n', encoding="utf-8")
    (b / "docker").write_text(f'#!/bin/sh\necho "docker $* MLP_GIT_SHA=$MLP_GIT_SHA" >> "{log}"\nexit 0\n', encoding="utf-8")
    for f in b.iterdir():
        f.chmod(0o755)
    return SimpleNamespace(bin=b, log=log)


def run(fake, status: str):
    env = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS")}
    env.update(PATH=f"{fake.bin}{os.pathsep}{env['PATH']}", FAKE_STATUS=status)
    r = subprocess.run(["make", "-s", "-C", str(ROOT), "image"], capture_output=True, text=True, env=env, timeout=60)
    calls = fake.log.read_text(encoding="utf-8").splitlines() if fake.log.exists() else []
    return r, [c for c in calls if c.startswith("docker")]


def test_dirty_tree_is_refused(fake):
    r, docker = run(fake, " M src/mlcore/x.py\n")
    assert r.returncode == 2 and docker == [] and "F7-5" in r.stdout


def test_clean_tree_builds_with_commit_sha(fake):
    r, docker = run(fake, "")
    assert r.returncode == 0, r.stdout + r.stderr
    assert docker == ["docker compose build app MLP_GIT_SHA=abc1234"]


def test_bench_tag_marks_dirty_tree(monkeypatch):
    sys.path.insert(0, str(ROOT / "gates"))
    import bench

    def fake_run(args, **kw):
        out = {"status": "", "diff": b"", "ls-files": ""}
        return SimpleNamespace(stdout=out.get(args[1], ""), returncode=0)
    monkeypatch.setattr(bench.subprocess, "run", fake_run)
    assert bench.image_tag("abc1234") == ("abc1234", False)

    def dirty_run(args, **kw):
        if args[1] == "status":
            return SimpleNamespace(stdout=" M a.py\n", returncode=0)
        return SimpleNamespace(stdout=b"diff" if args[1] == "diff" else "", returncode=0)
    monkeypatch.setattr(bench.subprocess, "run", dirty_run)
    tag, dirty = bench.image_tag("abc1234")
    assert dirty and tag.startswith("abc1234-wt") and len(tag) == len("abc1234-wt") + 8
