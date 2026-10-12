"""모델 산출물 — 저장 · 해시 · 적재 대조 (spec §6.2 · contracts/interfaces.md §5). 소유 개발2.

`var/artifacts/<tenant>/<task>/<version 또는 run>/` 아래 4개 파일:
  model.joblib · report.json · features.lock.json · env.lock
산출물 해시 = sha256( "<파일 이름>\\0<파일 sha256>\\n" 를 파일 이름순으로 이은 바이트 ).
적재할 때마다 해시와 패키지 버전(env.lock)을 대조하고, 다르면 ArtifactMismatch(503 model_artifact_mismatch).
대체 모델 · 기본값으로 넘어가지 않는다.
"""

from __future__ import annotations

import hashlib
import io
import json
import platform
import threading
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable, Mapping

import joblib

from ..serve.errors import ServeError
from ..settings import ROOT

FILES = ("env.lock", "features.lock.json", "model.joblib", "report.json")   # 이름순
LOCKED_PACKAGES = ("numpy", "pandas", "scikit-learn", "scipy", "joblib")


class ArtifactMismatch(ServeError):
    status, code, default_message = 503, "model_artifact_mismatch", "모델 산출물이 등록부와 다릅니다 (해시 · 패키지 버전 불일치)"


def resolve_dir(path: str | Path) -> Path:
    """등록부의 artifact_path 는 저장소 루트 기준 상대 경로(또는 절대 경로)다."""
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def store_path(path: str | Path) -> str:
    p = Path(path).resolve()
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def current_env_lock() -> dict:
    """지금 프로세스의 패키지 버전. 산출물 env.lock 과 정확히 같아야 적재한다."""
    pkgs = {}
    for name in LOCKED_PACKAGES:
        try:
            pkgs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pkgs[name] = None
    major, minor, _ = platform.python_version_tuple()
    return {"python": f"{major}.{minor}", "packages": pkgs}


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_sha256(version_dir: str | Path) -> str:
    d = Path(version_dir)
    h = hashlib.sha256()
    for name in FILES:
        p = d / name
        if not p.is_file():
            raise ArtifactMismatch(detail={"rule": "file_missing", "field": name})
        h.update(f"{name}\0{_sha_file(p)}\n".encode())
    return h.hexdigest()


def _read_all(d: Path) -> dict[str, bytes]:
    """4개 파일을 **한 번씩** 메모리로 읽는다 — 해시를 잰 바이트가 곧 적재하는 바이트다(TOCTOU 0, DEF-QA2-005)."""
    out = {}
    for name in FILES:
        try:
            out[name] = (d / name).read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            raise ArtifactMismatch(detail={"rule": "file_missing", "field": name}) from None
    return out


def bytes_sha256(blobs: Mapping[str, bytes]) -> str:
    """artifact_sha256 과 같은 규칙(파일 이름순 "<이름>\0<sha256>\n")을 메모리 바이트에 적용."""
    h = hashlib.sha256()
    for name in FILES:
        h.update(f"{name}\0{hashlib.sha256(blobs[name]).hexdigest()}\n".encode())
    return h.hexdigest()


def _dump_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1, default=str), encoding="utf-8")


def save_artifacts(version_dir: str | Path, model: object, report: dict, features_lock: dict) -> str:
    """4개 파일을 쓰고 산출물 해시를 돌려준다. 학습기(개발1)가 부른다."""
    d = Path(version_dir)
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, d / "model.joblib")
    _dump_json(d / "report.json", report)
    _dump_json(d / "features.lock.json", features_lock)
    _dump_json(d / "env.lock", current_env_lock())
    return artifact_sha256(d)


def features_lock(order: Iterable[str], features: Mapping[str, dict], *, ranges: Mapping[str, dict],
                  fills: Mapping[str, Any], baseline: float | None, interval: dict | None = None) -> dict:
    """features.lock.json 모양을 만든다 (progress-dev2.md §1.4).

    features: 병합된 변수 정의(dtype) · ranges: 스냅숏 학습 범위 {p1, p99} | {values} · fills: 학습 구간 보정값.
    """
    out: dict[str, dict] = {}
    for name in order:
        f = features[name]
        r = ranges.get(name) or {}
        item: dict[str, Any] = {"dtype": f.get("dtype"), "fill": fills.get(name)}
        if f.get("dtype") == "category":
            item["values"] = list(r.get("values") or [])
        else:
            item["p1"], item["p99"] = r.get("p1"), r.get("p99")
        out[name] = item
    return {"order": list(order), "features": out, "baseline": baseline, "interval": interval}


@dataclass(frozen=True)
class LoadedModel:
    model: Any
    report: dict
    lock: dict
    env_lock: dict
    sha256: str
    version: str
    algo: str


_CACHE: dict[tuple, LoadedModel] = {}
_LOCK = threading.Lock()


def _stat_key(d: Path) -> tuple:
    out = []
    for name in FILES:
        p = d / name
        try:
            st = p.stat()
        except FileNotFoundError:
            raise ArtifactMismatch(detail={"rule": "file_missing", "field": name}) from None
        out.append((name, st.st_mtime_ns, st.st_size, st.st_ino))
    return tuple(out)


def load_artifacts(ref) -> LoadedModel:
    """ModelRef → LoadedModel. 해시 · env.lock(파일) · env_lock(등록부) · 현재 패키지 버전을 모두 대조한다.

    같은 파일 상태(mtime · 크기 · inode)면 대조 결과를 재사용한다 — 파일이 바뀌면 다시 해시를 잰다.
    """
    d = resolve_dir(ref.artifact_path)
    if not d.is_dir():
        raise ArtifactMismatch(detail={"rule": "dir_missing", "field": None})
    key = (str(d.resolve()), ref.artifact_sha256, _stat_key(d))
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        _check_env(hit.env_lock, getattr(ref, "env_lock", None))
        return hit
    blobs = _read_all(d)                         # 해시 · 적재가 같은 바이트 — 그 사이 파일이 바뀌어도 검증한 바이트만 쓴다
    digest = bytes_sha256(blobs)
    if digest != ref.artifact_sha256:
        raise ArtifactMismatch(detail={"rule": "sha256", "field": None})
    env_file = json.loads(blobs["env.lock"].decode("utf-8"))
    _check_env(env_file, getattr(ref, "env_lock", None))
    loaded = LoadedModel(
        model=joblib.load(io.BytesIO(blobs["model.joblib"])),
        report=json.loads(blobs["report.json"].decode("utf-8")),
        lock=json.loads(blobs["features.lock.json"].decode("utf-8")),
        env_lock=env_file, sha256=digest, version=ref.version, algo=ref.algo)
    with _LOCK:
        _CACHE.clear() if len(_CACHE) > 64 else None
        _CACHE[key] = loaded
    return loaded


def _check_env(env_file: dict, env_registry: dict | None) -> None:
    now = current_env_lock()
    if env_registry is not None and env_registry != env_file:
        raise ArtifactMismatch(detail={"rule": "env_lock_registry", "field": None})
    if env_file != now:
        diff = sorted(k for k in set(now["packages"]) | set(env_file.get("packages") or {})
                      if (env_file.get("packages") or {}).get(k) != now["packages"].get(k))
        if env_file.get("python") != now["python"]:
            diff.append("python")
        raise ArtifactMismatch(detail={"rule": "env_lock", "field": ",".join(diff) or None})
