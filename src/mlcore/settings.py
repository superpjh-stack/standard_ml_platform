"""설정 — 환경변수 접두 MLP_ (D-15). 값은 .env 또는 배포 비밀에서만 온다. 코드에 기본 비밀값은 없다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """저장소 루트 .env 를 읽는다(있으면). 이미 있는 환경변수는 덮지 않는다."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.startswith("MLP_") and value:
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    db_dsn: str
    test_db_dsn: str
    tenant: str | None
    api_port: int
    web_port: int
    artifact_dir: Path
    snapshot_dir: Path
    cors_origins: tuple[str, ...]
    code_version: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    env = os.environ.get
    return Settings(
        db_dsn=env("MLP_DB_DSN") or "dbname=ml_db host=/tmp",
        test_db_dsn=env("MLP_TEST_DB_DSN") or "dbname=ml_test_db host=/tmp",
        tenant=env("MLP_TENANT") or None,
        api_port=int(env("MLP_API_PORT") or 8200),
        web_port=int(env("MLP_WEB_PORT") or 5190),
        artifact_dir=Path(env("MLP_ARTIFACT_DIR") or ROOT / "var" / "artifacts"),
        snapshot_dir=Path(env("MLP_SNAPSHOT_DIR") or ROOT / "var" / "snapshots"),
        cors_origins=tuple(o for o in (env("MLP_CORS_ORIGINS") or "").split(",") if o),
        code_version=env("MLP_CODE_VERSION") or "dev",
    )
