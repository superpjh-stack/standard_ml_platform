"""G-M01 — 코어 순수성. `src/mlcore/` · `web/src/` 에 팩 변수 · 과제 · 목표 이름 · 회사 코드 · 회사명 · 원천 테이블 0건.
`packs/` 에 회사 코드 · 회사명 · 원천 테이블 · 회사 범주값(설비 코드 등) 0건. (spec §16.1 · goal §2.2)

`_template` 팩의 이름(x1 · c1 …)은 업종어가 아닌 자리표시라 금지어에서 뺀다.
"""
from gatelib import ROOT, Line, read, rel, show, tenant_words, word_pattern

CORE_SUFFIX = {".py", ".sql", ".ts", ".tsx", ".js", ".css", ".html"}


def _scan(files, needles):
    hits = []
    for f in files:
        txt = read(f)
        for label, pat in needles.items():
            m = pat.search(txt)
            if m:
                line = txt[: m.start()].count("\n") + 1
                hits.append(f"{rel(f)}:{line}:'{label}'")
    return hits


def run() -> list[Line]:
    from mlcore.registry import packs
    pack_terms = {}
    loaded = 0
    for code in packs.all_codes():
        if code.startswith("_"):
            continue
        for w in packs.terms(packs.load_pack(code)):
            pack_terms[w] = word_pattern(w)
        loaded += 1
    names, tables, cats = tenant_words()
    core_files = [p for p in (ROOT / "src" / "mlcore").rglob("*") if p.is_file() and p.suffix in CORE_SUFFIX and "__pycache__" not in p.parts]
    core_files += [p for p in (ROOT / "web" / "src").rglob("*") if p.is_file() and p.suffix in CORE_SUFFIX]
    pack_files = [p for p in (ROOT / "packs").rglob("*") if p.is_file() and p.suffix in (".py", ".yaml", ".md") and "__pycache__" not in p.parts]
    if loaded == 0 or not names:
        return [Line("G-M01", "코어 순수성", "FAIL", f"금지어 사전 비어 있음 (팩 {loaded} · 회사 {len(names)}) — 검사 불가")]
    core_hits = _scan(core_files, {**pack_terms, **names, **tables})
    pack_hits = _scan(pack_files, {**names, **tables, **cats})
    hits = core_hits + pack_hits
    sizes = f"금지어 팩 {len(pack_terms)} · 회사 {len(names)} · 테이블 {len(tables)} · 범주값 {len(cats)}"
    if hits:
        return [Line("G-M01", "코어 순수성", "FAIL", f"{len(hits)}건: " + "; ".join(hits[:6]) + (" …" if len(hits) > 6 else ""))]
    return [Line("G-M01", "코어 순수성", "PASS", f"코어 {len(core_files)}파일 · 팩 {len(pack_files)}파일 위반 0 ({sizes})")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
