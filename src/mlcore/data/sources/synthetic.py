"""synthetic 어댑터 — 팩 합성 생성기 `generate(rows, seed, *, categories)` 를 부른다 (spec §4.1 · pack-contract §4 · D-53).

생성기는 두 길로 받는다:
  - `SyntheticSource.from_call(call)` — 회사 등록부 해석(`registry.tenants.synth_call`: 과제 진입점 synth/<task>.py
    또는 pack.yaml synth.module, 시드 · 행 수 · 회사 범주값)을 그대로 쓴다. 학습 작업의 기본 길.
  - `SyntheticSource(pack_dir, module, seed=…, rows=…)` — 생성기 파일을 경로로 동적 로드(상대 import 없는 모듈).
코어는 생성기 내용을 모른다. 생성기가 없으면 합성 값을 지어내지 않고 SourceDisconnected 를 올린다. 읽기 전용.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
from pathlib import Path
from typing import Callable

import pandas as pd

from ..frame import missing_rates, standardize
from .base import ReadSpec, SourceDisconnected, SourceHealth


def _load_file(path: Path) -> Callable:
    if not path.is_file():
        raise SourceDisconnected("synthetic", f"합성 생성기 없음: {path.parent.parent.name}/{path.parent.name}/{path.name}")
    name = "mlp_synth_" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # 생성기 오류는 숨기지 않는다
        raise SourceDisconnected("synthetic", f"합성 생성기 로드 실패: {type(e).__name__}: {e}") from e
    gen = getattr(mod, "generate", None)
    if not callable(gen):
        raise SourceDisconnected("synthetic", f"{path.name}: generate() 없음")
    return gen


class SyntheticSource:
    kind = "synthetic"

    def __init__(self, pack_dir: str | Path | None = None, module: str | None = None, *, seed: int, rows: int,
                 categories: dict | None = None, generate: Callable | None = None, source_ref: dict | None = None):
        self.pack_dir = Path(pack_dir) if pack_dir is not None else None
        self.module = module
        self.seed = int(seed)
        self.rows = int(rows)
        self.categories = dict(categories or {})
        self._generate_fn = generate
        self._ref = dict(source_ref) if source_ref else None

    @classmethod
    def from_call(cls, call) -> "SyntheticSource":
        """registry.tenants.SynthCall → 어댑터 (개발3 progress-dev3.md §1)."""
        return cls(seed=call.seed, rows=call.rows, categories=call.categories,
                   generate=lambda rows, seed, categories=None: call.generate(rows, seed), source_ref=call.source_ref)

    def _fn(self) -> Callable:
        if self._generate_fn is not None:
            return self._generate_fn
        if self.pack_dir is None or not self.module:
            raise SourceDisconnected(self.kind, "합성 생성기 지정 없음")
        return _load_file(self.pack_dir / self.module)

    def _generate(self) -> pd.DataFrame:
        gen = self._fn()
        kw = {}
        try:
            if "categories" in inspect.signature(gen).parameters:
                kw["categories"] = self.categories or None
        except (TypeError, ValueError):
            pass
        try:
            df = gen(self.rows, self.seed, **kw)
        except SourceDisconnected:
            raise
        except (ImportError, FileNotFoundError, KeyError) as e:
            raise SourceDisconnected(self.kind, f"합성 생성기 실패: {type(e).__name__}: {e}") from e
        if not isinstance(df, pd.DataFrame):
            raise SourceDisconnected(self.kind, "generate() 가 DataFrame 을 내지 않았다")
        return df

    def source_ref(self) -> dict:
        if self._ref is not None:
            return dict(self._ref)
        p = self.pack_dir / self.module if self.pack_dir is not None and self.module else None
        digest = hashlib.sha256(p.read_bytes()).hexdigest() if p is not None and p.is_file() else None
        return {"kind": self.kind, "module": f"{self.pack_dir.name}/{self.module}" if p else None,
                "synth_sha256": digest, "seed": self.seed, "rows": self.rows}

    def _ref_str(self) -> str:
        r = self.source_ref()
        return f"synth:{r.get('module')}?seed={self.seed}&rows={self.rows}"

    def read(self, spec: ReadSpec) -> pd.DataFrame:
        return standardize(self._generate(), spec, kind=self.kind, source_ref=self._ref_str())

    def probe(self, spec: ReadSpec | None = None) -> SourceHealth:
        try:
            if spec is None:
                raw = self._generate()
                return SourceHealth(self.kind, True, len(raw), None, None, 0.0, None, {}, None, "합성 생성기 정상")
            frame = self.read(spec)
        except SourceDisconnected as e:
            return SourceHealth(self.kind, False, None, None, None, None, None, {}, None, e.reason)
        names = [f.name for f in spec.features]
        cover = sum(bool(frame[n].notna().any()) for n in names) / len(names) if names else None
        needs_target = bool((spec.task.raw.get("target") or {}).get("name"))
        has_target = ("target" in frame.columns and bool(frame["target"].notna().any())) if needs_target else None
        ts = frame["ts"].dropna()
        return SourceHealth(self.kind, True, len(frame), ts.min().to_pydatetime() if len(ts) else None,
                            ts.max().to_pydatetime() if len(ts) else None, 0.0, cover,
                            missing_rates(frame, names), has_target,
                            "목표 없음" if has_target is False else "합성 생성기 정상")
