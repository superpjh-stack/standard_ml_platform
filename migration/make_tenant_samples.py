"""회사 예시 파일 생성기 — `tenants/<code>/samples/` (D2-A2-04 · 웨이브 P 재진입 D2-70).

회사 값(회사 재질 이름 · 회사 도면 번호 · 회사 참조 데이터)이 든 예시는 팩에 둘 수 없어(G-M01 — 팩은 회사를 모른다)
회사 폴더에 둔다. 호환 라우터 `pack_file` · `document_demo` 는 회사 폴더를 먼저 찾는다.

    uv run python migration/make_tenant_samples.py            # kd · ot 둘 다
    uv run python migration/make_tenant_samples.py --check    # 다시 만들어 저장본과 같은지만 본다(쓰기 0)

- kd `KD-demo-reactor.dxf` — 원천 `KyungDong ML AI/api/cad.py:16-39 sample_bytes()` 와 같은 도형 · 텍스트. 팩 생성기
  `packs/eto/synth/sample_dxf.py` 에 회사 재질 목록(`tenants/kd.yaml categories.main_material`, 원천 순서)을 주고, 표제란 도면
  번호만 원천 값(`KD-DEMO-R1000`, cad.py:27)으로 둔다. 내려받기 이름 = 원천 `KD-demo-reactor.dxf`(main.py:79 · :84).
- ot `demo.json` — 원천 `OneTouch ML AI/data/demo/{manifest,cad_object_candidates_20,quote_candidates_20}.json`
  (main.py:56-67 `/api/data/demo` 가 읽는 3 파일)을 **읽기만** 해서 `{manifest, cad, quotes}` 한 파일로. 이 저장소는 공개라
  원본 도면 파일 이름 · 제품명 · 제품 모델 코드는 옮기지 않는다(D2-65 — IP): 그 값은 `비공개` 로, id 의 제품 모델 코드
  토막은 지운다. 수치(치수 · 홀 · 견적 금액 — 원천이 합성한 값)와 상태 문구 · 제한사항은 그대로다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT.parent
OT_DEMO = SOURCES / "OneTouch ML AI" / "data" / "demo"
REDACTED = "비공개"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # type: ignore[union-attr]
    return mod


def kd_sample() -> bytes:
    sd = _load(ROOT / "packs" / "eto" / "synth" / "sample_dxf.py", "eto_sample_dxf_mk")
    cfg = yaml.safe_load((ROOT / "tenants" / "kd.yaml").read_text(encoding="utf-8"))
    ents = sd.entities(cfg["categories"]["main_material"])
    ents = [(c, "DRAWING NO: KD-DEMO-R1000" if (c, v) == (1, "DRAWING NO: DEMO-R1000") else v) for c, v in ents]   # cad.py:27
    return sd.dxf_bytes(ents)


def _redact(obj, secrets: list[str], codes: list[str]):
    if isinstance(obj, dict):
        return {k: _redact(v, secrets, codes) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v, secrets, codes) for v in obj]
    if isinstance(obj, str):
        if obj in secrets:
            return REDACTED
        for c in codes:
            obj = obj.replace(f"-{c}-", "-")
        return obj
    return obj


def ot_demo() -> bytes:
    manifest = json.loads((OT_DEMO / "manifest.json").read_text(encoding="utf-8"))
    cad = json.loads((OT_DEMO / "cad_object_candidates_20.json").read_text(encoding="utf-8"))
    quotes = json.loads((OT_DEMO / "quote_candidates_20.json").read_text(encoding="utf-8"))
    src = manifest.get("source") or {}
    secrets = sorted({str(v) for k, v in src.items() if k in ("pdf", "cad", "product")}
                     | {str(r[k]) for r in cad + quotes for k in ("source_pdf", "source_cad", "source_product") if k in r})
    # 제품 모델 코드 = 원본 PDF 이름의 마지막 토막(예 <도면번호>-<모델>.pdf) — id 에서 지운다
    codes = sorted({m.group(1) for s in secrets for m in [re.search(r"-([A-Z0-9]+)\.pdf$", s)] if m})
    doc = {"manifest": _redact(manifest, secrets, codes), "cad": _redact(cad, secrets, codes),
           "quotes": _redact(quotes, secrets, codes)}
    doc["manifest"]["redacted"] = "원본 도면 파일 이름 · 제품명 · 제품 모델 코드는 공개 저장소에 옮기지 않는다(D2-65)"
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    leak = [s for s in secrets + codes if s in text]
    if leak:
        raise SystemExit(f"가림 실패 — 남은 값 {len(leak)}개")
    return text.encode("utf-8")


TARGETS = {ROOT / "tenants" / "kd" / "samples" / "KD-demo-reactor.dxf": kd_sample,
           ROOT / "tenants" / "ot" / "samples" / "demo.json": ot_demo}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    bad = 0
    for path, make in TARGETS.items():
        data = make()
        if a.check:
            same = path.is_file() and path.read_bytes() == data
            bad += not same
            print(f"{path.relative_to(ROOT)}  {'같음' if same else '다름'}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"{path.relative_to(ROOT)}  {len(data)} bytes")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
