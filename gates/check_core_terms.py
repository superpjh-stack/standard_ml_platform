"""G-M01 — 코어 순수성. `src/mlcore/` · `web/src/` 에 팩 변수 · 과제 · 목표 이름 · 회사 코드 · 회사명 · 원천 테이블 0건.
`packs/` 에 회사 코드 · 회사명 · 원천 테이블 · 회사 범주값(설비 코드 등) 0건. (spec §16.1 · goal §2.2)

`_template` 팩의 이름(x1 · c1 …)은 업종어가 아닌 자리표시라 금지어에서 뺀다.

std 어휘(D2-31 — 아키텍트 결정): 과제 유형 코드 · 상태 코드 · 오류 코드 · 지표 · 기준선 이름(`std/*.yaml`)은 **코어의 말**이다.
코어는 유형 이름을 알아야 돌기 때문에(`tasks/base.py` · `schema.sql` …) 팩 과제 이름이 우연히 같다는 이유로 코어를 실패시키지 않는다.
완화가 아니라 더 엄격하다:
  - 팩 이름이 std 어휘와 겹치는 경우는 **과제 이름 = 그 과제 자신의 유형 코드**(예 과제 `quote` 의 type 이 `quote`) 하나만 허용한다.
    이때 코어에 그 단어가 있어도 뜻이 같은 std 유형이므로 코어 금지어에서 뺀다.
  - 그 밖의 겹침(변수 · 목표 · 비용식 이름이 std 어휘이거나, 과제 이름이 다른 유형의 코드)은 **팩 위반**으로 FAIL 한다
    (예전에는 코어 쪽에 우연히 그 단어가 있을 때만 걸렸다).
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


def std_vocabulary() -> set[str]:
    """std/*.yaml 의 코어 어휘 — 유형 · 상태 · 오류 코드 · 지표 · 기준선 이름."""
    from mlcore.registry import packs
    words = set(packs.std("task_types")["types"])
    st = packs.std("statuses")
    words |= set(st.get("statuses") or {}) | set(st.get("error_codes") or {})
    mt = packs.std("metrics")
    words |= set(mt.get("metrics") or {}) | set(mt.get("baselines") or {})
    return words


def std_collisions(pack, vocab: set[str]) -> tuple[set[str], list[str]]:
    """(코어 금지어에서 뺄 단어, 팩 위반) — 과제 이름 = 자기 유형 코드만 허용."""
    from mlcore.registry import packs
    allowed, bad = set(), []
    for w in sorted(packs.terms(pack) & vocab):
        t = pack.tasks.get(w)
        if t is not None and t.get("type") == w and w not in pack.features:
            allowed.add(w)
        else:
            bad.append(f"packs/{pack.code}:'{w}'(std 어휘와 같은 팩 이름 — 과제 이름 = 자기 유형 코드만 허용, D2-31)")
    return allowed, bad


def run() -> list[Line]:
    from mlcore.registry import packs
    pack_terms = {}
    loaded = 0
    vocab = std_vocabulary()
    std_bad: list[str] = []
    exempt: set[str] = set()
    for code in packs.all_codes():
        if code.startswith("_"):
            continue
        pack = packs.load_pack(code)
        allowed, bad = std_collisions(pack, vocab)
        exempt |= allowed
        std_bad += bad
        for w in packs.terms(pack):
            if w not in allowed:
                pack_terms[w] = word_pattern(w)
        loaded += 1
    for w in exempt:                       # 다른 팩이 같은 단어를 다른 뜻(변수 등)으로 쓰면 std_bad 에 이미 있다
        pack_terms.pop(w, None)
    names, tables, cats = tenant_words()
    core_files = [p for p in (ROOT / "src" / "mlcore").rglob("*") if p.is_file() and p.suffix in CORE_SUFFIX and "__pycache__" not in p.parts]
    core_files += [p for p in (ROOT / "web" / "src").rglob("*") if p.is_file() and p.suffix in CORE_SUFFIX]
    pack_files = [p for p in (ROOT / "packs").rglob("*") if p.is_file() and p.suffix in (".py", ".yaml", ".md") and "__pycache__" not in p.parts]
    if loaded == 0 or not names:
        return [Line("G-M01", "코어 순수성", "FAIL", f"금지어 사전 비어 있음 (팩 {loaded} · 회사 {len(names)}) — 검사 불가")]
    core_hits = _scan(core_files, {**pack_terms, **names, **tables})
    pack_hits = _scan(pack_files, {**names, **tables, **cats})
    hits = std_bad + core_hits + pack_hits
    sizes = (f"금지어 팩 {len(pack_terms)} · 회사 {len(names)} · 테이블 {len(tables)} · 범주값 {len(cats)} · "
             f"std 어휘 과제 이름 {len(exempt)}{sorted(exempt) if exempt else ''}")
    if hits:
        return [Line("G-M01", "코어 순수성", "FAIL", f"{len(hits)}건: " + "; ".join(hits[:6]) + (" …" if len(hits) > 6 else ""))]
    return [Line("G-M01", "코어 순수성", "PASS", f"코어 {len(core_files)}파일 · 팩 {len(pack_files)}파일 위반 0 ({sizes})")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
