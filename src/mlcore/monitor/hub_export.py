"""데이터 허브 내보내기 `mlp-hub-export/1` (contracts/hub-export.md · goal2 G2-I02 · D2-09 · D2-17). 소유 개발3.

    uv run python -m mlcore.monitor.hub_export [--date YYYY-MM-DD] [--out DIR]     # make export-hub [DATE=…]
    → var/export/hub/<date>.json (커밋 금지 — var/ 는 .gitignore)

등록부 회사 전부(`_template` 제외)의 **정의 · 대응 · 집계만** 낸다: 과제(MODEL) · 화면(SCREEN) · Agent 도구(TOOL) 소비자,
과제가 읽는 원천 테이블(datasets · usages — 합성 소스는 계보 없음 = physical_name null), 변수 대응(features), 일 호출 수(api_usage).
키 · DSN · URL · IP · 호스트 · 파일 경로 · 실데이터 행 · 입력값 · 예측값은 내지 않는다(등록부의 `*_env` 이름도 내지 않는다).
결정성: 같은 DB · 같은 날짜 → 같은 바이트(키 정렬 · 들여쓰기 2 · 목록 정렬, generated_at = 집계 창 끝 — decisions.md D2-32).
허브 저장소에는 쓰지 않는다. 허브 수확기가 이 파일을 읽게 하는 것은 허브 팀 일이다(D2-17).
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from ..registry import packs, tenants
from ..settings import ROOT, get_settings

FORMAT = "mlp-hub-export/1"
SYSTEM = {"kind": "ML", "name": "Standard ML Platform"}
KST = timezone(timedelta(hours=9))
OUT_DIR = ROOT / "var" / "export" / "hub"
LEARNED = ("regression", "risk", "anomaly")
TYPE_PATH = {"regression": "predict", "risk": "predict", "anomaly": "predict", "optimize": "optimize",
             "review_queue": "review", "extract": "documents", "quote": "quotes"}
# 화면 → 그 화면을 쓰는 과제 유형 (contracts/screen-map.md 표 — 1 · 5 · 7 · 10 은 회사 전체)
SCREEN_TYPES = {1: None, 2: LEARNED, 3: ("optimize",), 4: LEARNED, 5: None, 6: LEARNED, 7: None,
                8: ("review_queue",), 9: ("extract", "quote"), 10: None}
# Agent 도구(contracts/agent-tools.md §0 Agent 이름) → 그 도구가 부를 수 있는 과제 유형
TOOL_TYPES = {"ml.calculate_prediction": LEARNED, "ml.get_explanation": LEARNED,
              "ml.calculate_recommendation": ("optimize",), "ml.get_monitor_summary": None}


def _line_of(path: Path, pattern: str) -> int:
    """파일에서 정규식이 처음 맞는 줄 번호(1부터). 없으면 1."""
    rx = re.compile(pattern)
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if rx.search(line):
            return i
    return 1


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return p.name


def day_bounds(day: date) -> tuple[datetime, datetime]:
    lo = datetime.combine(day, time(0, 0), tzinfo=KST)
    return lo, lo + timedelta(days=1)


def _types(m: tenants.Merged) -> set[str]:
    return {td.type for td in m.tasks.values()}


def _applies(types: set[str], wanted) -> bool:
    return wanted is None or bool(types & set(wanted))


def api_path(code: str, td: tenants.TaskDef) -> str:
    return f"/api/v1/tenants/{code}/tasks/{td.id.split('.', 1)[1]}/{TYPE_PATH[td.type]}"


# ── 소비자 ────────────────────────────────────────────────────────────────────

def consumers(m: tenants.Merged, production: dict[str, dict]) -> list[dict]:
    code, mode = m.tenant.code, m.tenant.config["mode"]
    out = []
    for td in m.tasks.values():
        short = td.id.split(".", 1)[1]
        prod = production.get(td.id)
        out.append({"kind": "MODEL", "code": f"ML:{td.id}", "name": str(td.raw.get("title") or short)[:120],
                    "state": prod["version"] if prod else ("운영 모델 없음" if td.type in LEARNED else None),
                    "synthetic": bool(prod["synthetic"]) if prod else mode != "live",
                    "origin": "MLP", "source_ref": f"packs/{m.pack.code}/tasks/{short}.yaml:1"})
    types = _types(m)
    screen_map = ROOT / "contracts" / "screen-map.md"
    for n, wanted in SCREEN_TYPES.items():
        if _applies(types, wanted):
            title = _screen_title(screen_map, n)
            out.append({"kind": "SCREEN", "code": f"ML-S{n}", "name": title, "state": None,
                        "synthetic": mode != "live", "origin": "MLP",
                        "source_ref": f"contracts/screen-map.md:{_line_of(screen_map, rf'^\| {n} \|')}"})
    tools = ROOT / "contracts" / "agent-tools.md"
    for name, wanted in TOOL_TYPES.items():
        if _applies(types, wanted):
            out.append({"kind": "TOOL", "code": f"tool:{name}", "name": name, "state": None, "synthetic": mode != "live",
                        "origin": "MLP", "source_ref": f"contracts/agent-tools.md:{_line_of(tools, re.escape(f'`{name}`'))}"})
    return out


def _screen_title(path: Path, n: int) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {n} |"):
            return line.split("|")[2].strip()[:120]
    return f"화면 {n}"


# ── 원천 테이블 · 계보 ─────────────────────────────────────────────────────────

def _tables(cfg: dict) -> list[str]:
    """등록부가 이름을 아는 원천 테이블 · 뷰 — feature_map · target_map 키의 TABLE + sources 의 tables · table · view.
    합성 · CSV 소스는 테이블이 아니다(계보 없음). 값이 null(미확인)인 뷰는 내지 않는다."""
    names: set[str] = set()
    for key in list((cfg.get("feature_map") or {})) + list((cfg.get("target_map") or {})):
        names.add(str(key).split(".", 1)[0])
    for src in (cfg.get("sources") or {}).values():
        src = src or {}
        if src.get("kind") in ("synthetic", "csv"):
            continue
        names.update(str(t) for t in src.get("tables") or [] if t)
        for k in ("table", "view"):
            if src.get(k):
                names.add(str(src[k]))
    return sorted(names)


def datasets(m: tenants.Merged) -> list[dict]:
    path = m.tenant.path
    return [{"physical_name": t, "layer": "L5", "source_ref": f"{_rel(path)}:{_line_of(path, re.escape(t))}"}
            for t in _tables(m.tenant.config)]


def task_inputs(td: tenants.TaskDef) -> list[tuple[str, str]]:
    raw = td.raw
    out = [(f, "feature") for f in raw.get("features") or []]
    out += [(f, "control") for f in raw.get("controls") or []]
    out += [(f, "fixed") for f in raw.get("fixed") or []]
    tgt = (raw.get("target") or {}).get("name") if isinstance(raw.get("target"), dict) else None
    if tgt:
        out.append((tgt, "target"))
    return out


def usages(m: tenants.Merged) -> list[dict]:
    cfg, path = m.tenant.config, m.tenant.path
    fmap = cfg.get("feature_map") or {}
    tmap = cfg.get("target_map") or {}
    out = []
    for td in m.tasks.values():
        names = {f for f, _ in task_inputs(td)}
        tables = sorted({str(k).split(".", 1)[0] for k, v in fmap.items() if v in names}
                        | {str(k).split(".", 1)[0] for k, v in tmap.items() if v in names})
        ap = api_path(m.tenant.code, td)
        if not tables:
            out.append({"consumer_code": f"ML:{td.id}", "physical_name": None, "api_path": ap, "declared_in": "packs",
                        "source_ref": f"packs/{m.pack.code}/tasks/{td.id.split('.', 1)[1]}.yaml:1"})
        for t in tables:
            out.append({"consumer_code": f"ML:{td.id}", "physical_name": t, "api_path": ap, "declared_in": "tenants",
                        "source_ref": f"{_rel(path)}:{_line_of(path, re.escape(t) + r'\.')}"})
    return out


def features(m: tenants.Merged) -> list[dict]:
    fmap = m.tenant.config.get("feature_map") or {}
    tmap = m.tenant.config.get("target_map") or {}
    rev: dict[str, str] = {}
    for k, v in sorted({**fmap, **tmap}.items()):
        rev.setdefault(str(v), str(k))
    std_names = m.pack.std_name or {}
    out = []
    for td in m.tasks.values():
        for name, role in task_inputs(td):
            col = rev.get(name)
            out.append({"task": td.id, "std_name": str(std_names.get(name) or f"{m.pack.code}.{name}"), "role": role,
                        "source_column": col, "mapped": col is not None})
    return out


# ── 일 호출 수 (허브 M5 fixture 모양) ─────────────────────────────────────────────

def api_usage(m: tenants.Merged, day: date, *, conn) -> dict:
    code = m.tenant.code
    lo, hi = day_bounds(day)
    preds = conn.execute("SELECT task_id, channel, count(*) AS n FROM mlp_prediction WHERE tenant_id=%s AND ts >= %s AND ts < %s "
                         "GROUP BY task_id, channel", (code, lo, hi)).fetchall()
    audits = conn.execute("SELECT target, detail FROM mlp_audit WHERE tenant_id=%s AND ts >= %s AND ts < %s",
                          (code, lo, hi)).fetchall()
    recorded = bool(preds or audits)
    by_task: dict[str, dict[str, int]] = {}
    for r in preds:
        by_task.setdefault(r["task_id"], {})[r["channel"]] = int(r["n"])
    out: dict[str, dict] = {}
    for td in m.tasks.values():
        ap = api_path(code, td)
        if not recorded:
            out[ap] = {"calls": None, "errors": None, "p95_ms": None, "ref": f"mlp_prediction@{day.isoformat()}", "basis": "미확인"}
            continue
        hits = [a for a in audits if str(a["target"] or "").startswith(ap)]
        errors = sum(1 for a in hits if int((a["detail"] or {}).get("status", 200)) >= 400)
        if td.type in ("regression", "risk", "anomaly", "optimize"):
            ch = by_task.get(td.id, {})
            calls = sum(ch.values())
            ref = f"mlp_prediction@{day.isoformat()}" + (" (" + " · ".join(f"{k} {v}" for k, v in sorted(ch.items())) + ")" if ch else "")
        else:                                   # 대기열 · 문서 · 견적은 예측 행이 아니다 — 감사 행(쓰기 요청)으로 센다
            calls = len(hits)
            ref = f"mlp_audit@{day.isoformat()}"
        out[ap] = {"calls": calls, "errors": errors, "p95_ms": None, "ref": ref, "basis": "실측"}   # 지연 기록 없음 → p95 null
    return {day.isoformat(): dict(sorted(out.items()))}


# ── 묶기 ──────────────────────────────────────────────────────────────────────

def production_rows(code: str, *, conn) -> dict[str, dict]:
    rows = conn.execute("SELECT task_id, version, synthetic FROM mlp_model_version WHERE tenant_id=%s AND stage='production'",
                        (code,)).fetchall()
    return {r["task_id"]: r for r in rows}


def company(m: tenants.Merged, day: date, *, conn) -> dict:
    cfg = m.tenant.config
    order = {"MODEL": 0, "SCREEN": 1, "TOOL": 2}
    cons = sorted(consumers(m, production_rows(m.tenant.code, conn=conn)),
                  key=lambda c: (order[c["kind"]], c["kind"], _natural(c["code"])))
    return {"company": str(cfg.get("hub_company") or m.tenant.code), "mode": cfg["mode"], "consumers": cons,
            "datasets": sorted(datasets(m), key=lambda d: d["physical_name"]),
            "usages": sorted(usages(m), key=lambda u: (u["consumer_code"], u["physical_name"] or "", u["api_path"])),
            "features": sorted(features(m), key=lambda f: (f["task"], f["role"], f["std_name"])),
            "api_usage": api_usage(m, day, conn=conn)}


def _natural(s: str) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s))


def build(day: date, *, codes: list[str] | None = None) -> dict:
    from ..db.conn import connect

    codes = codes if codes is not None else tenants.all_codes()
    comps = []
    with connect() as c:
        for code in codes:
            comps.append(company(tenants.load_and_merge(code), day, conn=c))
    comps.sort(key=lambda x: x["company"])
    end = day_bounds(day)[1]
    return {"format": FORMAT, "generated_at": end.isoformat(), "date": day.isoformat(),
            "system": {**SYSTEM, "code_version": get_settings().code_version}, "companies": comps}


def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write(day: date, *, out_dir: Path | None = None, codes: list[str] | None = None) -> Path:
    out_dir = Path(out_dir) if out_dir is not None else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day.isoformat()}.json"
    path.write_text(dumps(build(day, codes=codes)), encoding="utf-8")
    return path


def yesterday_kst() -> date:
    return datetime.now(KST).date() - timedelta(days=1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="데이터 허브 내보내기 mlp-hub-export/1 (contracts/hub-export.md)")
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="집계 날짜 KST (기본 어제)")
    ap.add_argument("--out", type=Path, default=None, help="출력 폴더 (기본 var/export/hub)")
    a = ap.parse_args(argv)
    path = write(a.date or yesterday_kst(), out_dir=a.out)
    doc = json.loads(path.read_text(encoding="utf-8"))
    print(f"{_rel(path)}: 회사 {len(doc['companies'])} · 소비자 {sum(len(c['consumers']) for c in doc['companies'])} · "
          f"변수 {sum(len(c['features']) for c in doc['companies'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
