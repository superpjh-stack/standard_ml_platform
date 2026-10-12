"""QA2-3 — task-map 2차 4사(68 단위)를 원천 저장소와 표준 등록부에 대조한다. 원천은 읽기만.
사용: uv run python -I outputs/qa2-3/taskmap_check.py <repo_root> <원천 상위 폴더>
"""
import re, sys, pathlib, yaml
root = pathlib.Path(sys.argv[1]); src_parent = pathlib.Path(sys.argv[2])
CO = {"krs": ("Koreal Solder ML AI", "solder"), "pc": ("PyoungChang ML AI", "kimchi"),
      "ot": ("OneTouch ML AI", "rollform-quote"), "kd": ("KyungDong ML AI", "eto")}
PFX = {"krs": "KRS", "pc": "PC", "ot": "OT", "kd": "KD"}
tm = (root / "docs/task-map.md").read_text()
rows = [l.replace("\\|", "¦") for l in tm.splitlines() if re.match(r"\| (KRS|PC|OT|KD)-", l)]
out = []
def row(*a): out.append("  ".join(str(x) for x in a)); print(out[-1])
total = 0
for code, (repo, pack) in CO.items():
    rs = [r for r in rows if r.startswith(f"| {PFX[code]}-")]
    total += len(rs)
    main = (src_parent / repo / "api/main.py").read_text().splitlines()
    eps = [(i + 1, m.group(1).upper(), m.group(2)) for i, l in enumerate(main)
           if (m := re.search(r"@app\.(get|post|put|patch|delete)\(['\"]([^'\"]+)", l))]
    app = (src_parent / repo / "web/src/App.tsx").read_text()
    nav = re.findall(r"\{id:'(\w+)',name:'([^']+)'", app) or re.findall(r"type View=([^\n;]+)", app)
    e_rows = [r for r in rs if re.match(rf"\| {PFX[code]}-E\d", r)]
    s_rows = [r for r in rs if re.match(rf"\| {PFX[code]}-S\d", r)]
    web_root = 1 if code == "pc" and any("nginx" in r for r in e_rows) else 0  # pc GET / 는 web nginx(원천 API 밖)
    row(code, "원천 엔드포인트", len(eps), "+웹 루트", web_root, "task-map E", len(e_rows), "PASS" if len(eps) + web_root == len(e_rows) else "FAIL")
    nscreens = len(nav) if nav and isinstance(nav[0], tuple) else len(re.findall(r"'(\w+)'", nav[0]))
    row(code, "원천 화면", nscreens, "task-map S", len(s_rows), "PASS" if nscreens == len(s_rows) else "FAIL")
    # 원천 경로가 task-map E 행 문구에 있는가
    for ln, meth, p in eps:
        hit = [r for r in e_rows if f"`{meth} {p}" in r or (p == "/{path:path}" and "SPA" in r) or (p == "/" and "`GET /`" in r)]
        row(code, f"원천 {meth} {p} :{ln}", "task-map", "PASS" if hit else "FAIL(행 없음)")
    # 파일:줄 인용 검증 (api/main.py:a-b 꼴)
    for r in rs:
        for a, b in re.findall(r"api/main\.py:(\d+)(?:-(\d+))?", r):
            txt = main[int(a) - 1]
            ok = "@app." in txt or "@app." in "".join(main[int(a) - 2:int(a)])
            row(code, r.split("|")[1].strip(), f"main.py:{a}", "PASS" if ok else f"WARN 줄 내용={txt.strip()[:40]!r}")
    # 표준 대응: 과제 · 호환 경로
    ten = yaml.safe_load((root / f"tenants/{code}.yaml").read_text())
    routes = ten.get("compat", {}).get("routes", [])
    rpaths = {(x["path"] if isinstance(x, dict) else x) for x in routes}
    tasks = {p.stem for p in (root / f"packs/{pack}/tasks").glob("*.yaml")}
    tdir = root / f"tenants/{code}/tasks"
    if tdir.exists(): tasks |= {p.stem for p in tdir.glob("*.yaml")}
    for r in rs:
        cells = [c.strip() for c in r.split("|")[1:-1]]
        rid, task_cell, compat_cell = cells[0], cells[2], cells[5]
        for t in re.findall(rf"`{code}\.(\w+)`", task_cell):
            row(code, rid, f"과제 {code}.{t}", "PASS" if t in tasks else "FAIL(팩 · 회사 과제 없음)")
        m = re.match(r"`([^`]+)`", compat_cell)
        if m:
            row(code, rid, f"호환 {m.group(1)}", "PASS" if m.group(1) in rpaths else "FAIL(compat.routes 없음)")
    extra = rpaths - {re.match(r"`([^`]+)`", [c.strip() for c in r.split("|")[1:-1]][5]).group(1)
                      for r in rs if re.match(r"`", [c.strip() for c in r.split("|")[1:-1]][5])}
    row(code, "compat.routes 중 task-map 에 없는 경로", sorted(extra) or "0", "PASS" if not extra else "WARN")
row("합계 2차 단위", total, "기대 68", "PASS" if total == 68 else "FAIL")
(root / "outputs/qa2-3/taskmap_rows.txt").write_text("\n".join(out) + "\n")
