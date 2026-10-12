"""dataplatform 어댑터 — Data Platform REST 를 **GET 으로만** 읽는다 (spec §4.1). 읽기 전용(G-S05).

등록부 `sources.<name>`: `{kind: dataplatform, url_env, key_env, view, path?, params?, page_size?}`
- 주소 · 키 값은 등록부에 없다 — 환경변수 **이름**(`url_env` · `key_env`)으로 프로세스 환경에서만 읽는다.
  오류 문구에 주소 · 호스트 · 키를 넣지 않는다(HTTP 상태 · 예외 종류만).
- 요청: `GET <url><path>?view=<view>&<params>&limit=<page_size>[&cursor=…]`, 헤더 `x-api-key`.
  응답 `{items: [...], next_cursor}` (또는 `rows` · `next`)를 커서가 없을 때까지 따라간다.
  `path` 기본값 `/v1/readings` 는 회사 Data Platform 클라이언트 `get_readings` 를 따른 **가설**이다(뷰 이름 미확인 — D-32 · D-33).
- 한도(interfaces §2): 키당 5 req/s · 5,000 req/일 — 클라이언트에서 지킨다(초당은 기다리고, 일 한도는 실패를 보인다).
- 전송(transport)은 주입할 수 있다 — 시험은 가짜 전송을 쓰고 실제 호출을 하지 않는다(D-13).
  기본 전송은 표준 라이브러리 urllib 의 GET 하나뿐이다(본문 · 다른 메서드를 보내는 길이 없다).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Callable

import pandas as pd

from ..frame import health_from_frame, standardize
from .base import ReadSpec, SourceDisconnected, SourceHealth

DEFAULT_PATH = "/v1/readings"
PER_SECOND = 5
PER_DAY = 5000
MAX_PAGES = 1000

Transport = Callable[[str, dict], tuple[int, dict]]     # (url, headers) → (HTTP 상태, JSON 본문)


def urllib_get(url: str, headers: dict, timeout: float = 30.0) -> tuple[int, dict]:
    """기본 전송 — GET 만. 본문을 보내지 않는다."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 — 주소는 운영자가 넣은 환경변수
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            body = {}
        return e.code, body


class RateLimiter:
    """키당 초당 · 일 한도. 시계 · 잠은 주입할 수 있다(시험)."""

    def __init__(self, per_second: int = PER_SECOND, per_day: int = PER_DAY, *,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 today: Callable[[], date] = date.today):
        self.per_second, self.per_day = per_second, per_day
        self.clock, self.sleep, self.today = clock, sleep, today
        self._recent: list[float] = []
        self._day, self._count = None, 0
        self._lock = threading.Lock()

    def acquire(self, kind: str = "dataplatform") -> None:
        with self._lock:
            d = self.today()
            if d != self._day:
                self._day, self._count = d, 0
            if self._count >= self.per_day:
                raise SourceDisconnected(kind, f"일 요청 한도 {self.per_day:,} 초과 — 내일 다시")
            now = self.clock()
            self._recent = [t for t in self._recent if now - t < 1.0]
            if len(self._recent) >= self.per_second:
                self.sleep(1.0 - (now - self._recent[0]))
                now = self.clock()
                self._recent = [t for t in self._recent if now - t < 1.0]
            self._recent.append(now)
            self._count += 1

    @property
    def used_today(self) -> int:
        return self._count


_LIMITERS: dict[str, RateLimiter] = {}


def limiter_for(key: str) -> RateLimiter:
    """같은 키는 프로세스 안에서 한도를 나눠 쓴다(키 값은 해시로만 들고 있다)."""
    k = hashlib.sha256(key.encode()).hexdigest()[:16]
    return _LIMITERS.setdefault(k, RateLimiter())


class DataPlatformSource:
    kind = "dataplatform"

    def __init__(self, *, url_env: str | None, key_env: str | None, view: str | None = None,
                 path: str | None = None, params: dict | None = None, page_size: int = 1000,
                 transport: Transport | None = None, limiter: RateLimiter | None = None,
                 ts_column: str | None = None, entity_column: str | None = None):
        if not url_env or not key_env:
            raise SourceDisconnected(self.kind, "url_env · key_env 없음 (등록부)")
        self.url_env, self.key_env = url_env, key_env
        self.view = view
        self.path = path or DEFAULT_PATH
        self.params = dict(params or {})
        self.page_size = int(page_size)
        self.transport = transport or urllib_get
        self._limiter = limiter
        self.ts_column, self.entity_column = ts_column, entity_column

    @classmethod
    def from_config(cls, cfg: dict, *, transport: Transport | None = None,
                    limiter: RateLimiter | None = None) -> "DataPlatformSource":
        return cls(url_env=cfg.get("url_env"), key_env=cfg.get("key_env"), view=cfg.get("view"), path=cfg.get("path"),
                   params=cfg.get("params"), page_size=cfg.get("page_size", 1000), transport=transport,
                   limiter=limiter, ts_column=cfg.get("ts_column"), entity_column=cfg.get("entity_column"))

    def source_ref(self) -> dict:
        return {"kind": self.kind, "view": self.view, "path": self.path, "params": dict(sorted(self.params.items()))}

    def _endpoint(self) -> tuple[str, dict]:
        if not self.view and not self.params:
            raise SourceDisconnected(self.kind, "뷰 이름 미확인 (등록부 view: null)")
        for name in (self.url_env, self.key_env):
            if not os.environ.get(name):
                raise SourceDisconnected(self.kind, f"환경변수 {name} 가 비어 있다 (D-13 — 사람이 넣는다)")
        base = os.environ[self.url_env].rstrip("/")
        return base + "/" + self.path.lstrip("/"), {"x-api-key": os.environ[self.key_env], "accept": "application/json"}

    def _fetch(self, spec: ReadSpec | None) -> pd.DataFrame:
        url, headers = self._endpoint()
        limiter = self._limiter or limiter_for(headers["x-api-key"])
        q = {**self.params, "limit": self.page_size}
        if self.view:
            q["view"] = self.view
        if spec is not None and spec.ts_from is not None:
            q["from"] = pd.Timestamp(spec.ts_from).isoformat()
        if spec is not None and spec.ts_to is not None:
            q["to"] = pd.Timestamp(spec.ts_to).isoformat()
        rows, cursor = [], None
        for _ in range(MAX_PAGES):
            page_q = {**q, **({"cursor": cursor} if cursor else {})}
            limiter.acquire(self.kind)
            try:
                status, body = self.transport(url + "?" + urllib.parse.urlencode(sorted(page_q.items())), headers)
            except SourceDisconnected:
                raise
            except Exception as e:  # 네트워크 오류를 숨기지 않는다 — 종류만(주소 · 키 금지)
                raise SourceDisconnected(self.kind, f"요청 실패: {type(e).__name__}") from e
            if status != 200:
                raise SourceDisconnected(self.kind, f"HTTP {status}")
            items = body.get("items", body.get("rows"))
            if not isinstance(items, list):
                raise SourceDisconnected(self.kind, "응답에 items 목록이 없다")
            rows += items
            cursor = body.get("next_cursor", body.get("next"))
            if not cursor:
                break
        else:
            raise SourceDisconnected(self.kind, f"페이지 {MAX_PAGES} 초과 — 기간을 나눠 읽는다")
        df = pd.DataFrame(rows)
        if self.ts_column and self.ts_column in df.columns:
            df["ts"] = df[self.ts_column]
        if self.entity_column and self.entity_column in df.columns:
            df["entity_id"] = df[self.entity_column].astype(str)
        return df

    def read(self, spec: ReadSpec) -> pd.DataFrame:
        ref = f"dataplatform:{self.view or self.path}"
        return standardize(self._fetch(spec), spec, kind=self.kind, source_ref=ref)

    def probe(self, spec: ReadSpec | None = None) -> SourceHealth:
        try:
            if spec is None:
                raw = self._fetch(None)
                return SourceHealth(self.kind, True, len(raw), None, None, None, None, {}, None, "Data Platform 연결")
            frame = self.read(spec)
        except SourceDisconnected as e:
            return SourceHealth(self.kind, False, None, None, None, None, None, {}, None, e.reason)
        return health_from_frame(self.kind, frame, spec, "Data Platform 연결")
