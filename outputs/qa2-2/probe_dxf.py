"""QA2-2 §A DXF 파서 공격 · §B 업로드 상한 (B10 documents) — 고치지 않는다. 결과 → probe_dxf-result.json"""
from __future__ import annotations

import gzip
import importlib.util
import io
import json
import sys
import time
import tracemalloc
import zipfile

from common import ROOT, circle, client, count, dxf, h, line, rec, rect, save, text

MiB = 1024 * 1024


def load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    tmp = ROOT / "outputs" / "qa2-2" / ".tmp"
    tmp.mkdir(exist_ok=True)
    import tempfile
    base = __import__("pathlib").Path(tempfile.mkdtemp(prefix="qa22-dxf-"))
    m = h.make_tenant("kd", base)
    t = m.tenant.code
    k = h.keys(m)
    tc = client(m)
    url = f"/api/v1/tenants/{t}/tasks/{t}.drawing_regions/documents"
    op = h.hdr(k["operator"])

    def up(raw: bytes, name="a.dxf", key=op, unit=None, timeout_note=""):
        files = {"file": (name, raw, "application/dxf")}
        data = {"unit_override": unit} if unit else None
        t0 = time.perf_counter()
        r = tc.post(url, headers=key, files=files, data=data)
        dt = time.perf_counter() - t0
        try:
            body = r.json()
        except ValueError:
            body = {"_raw": r.text[:200]}
        return r.status_code, body, dt, len(r.content)

    def err(body):
        e = body.get("error") or {}
        return e.get("code"), (e.get("detail") or {}).get("rule")

    # 0. 정상 샘플
    mats = m.tenant.config["categories"]["main_material"]
    sample = load("packs/eto/synth/sample_dxf.py", "qa22_sample").sample_bytes(mats)
    s, b, dt, _ = up(sample, "sample.dxf")
    rec("G2-E01", "정상 샘플 업로드", s == 201 and b.get("labels") == "none" and b.get("metrics") is None,
        {"status": s, "labels": b.get("labels"), "metrics": b.get("metrics"), "regions": len(b.get("regions") or []),
         "bom": len(b.get("bom_rows") or []), "sec": round(dt, 3)})

    # 1. 엔티티 경계 20,000 / 20,001 (kd) — 주석 패딩 없이
    for n, want in ((20000, 201), (20001, 413)):
        ents = []
        for i in range(n):
            ents += line(0, i, 10, i)
        s, b, dt, size = up(dxf(ents))
        rec("G2-E01", f"kd 엔티티 {n:,}", s == want and (want == 201 or err(b) == ("document_too_large", "entities")),
            {"status": s, "err": err(b), "sec": round(dt, 2), "resp_bytes": size}, want)

    # 1b. 하위 레코드(VERTEX) 로 엔티티 수 피하기 — POLYLINE 1 + VERTEX 다수
    ents = [(0, "POLYLINE"), (8, "P"), (66, "1"), (70, "0")]
    for i in range(150000):
        ents += [(0, "VERTEX"), (8, "P"), (10, str(i)), (20, "0")]
    ents += [(0, "SEQEND")]
    raw = dxf(ents + text("BOM", 1, 1))
    s, b, dt, size = up(raw)
    rec("G2-E01", "POLYLINE + VERTEX 15만(엔티티 수 회피)", s in (201, 413, 422) and dt < 10,
        {"status": s, "err": err(b), "entity_count": b.get("entity_count"), "sec": round(dt, 2), "bytes": len(raw)})

    # 2. 5 MiB 경계 (999 주석 패딩) — 정확히 5 MiB 는 받고 +1 은 413 bytes
    core = dxf(text("BOM", 1, 1) + rect(0, 0, 10, 10))
    exact = dxf(text("BOM", 1, 1) + rect(0, 0, 10, 10), pad_comment=5 * MiB - len(core))
    over = dxf(text("BOM", 1, 1) + rect(0, 0, 10, 10), pad_comment=5 * MiB - len(core) + 1)
    for raw, want, label in ((exact, 201, "정확히 5 MiB"), (over, 413, "5 MiB + 1")):
        s, b, dt, _ = up(raw)
        rec("G2-E01", f"크기 {label} ({len(raw):,} B)", s == want and (want == 201 or err(b) == ("document_too_large", "bytes")),
            {"status": s, "err": err(b), "sec": round(dt, 2)}, want)

    # 2b. multipart 전체가 상한 + 64 KiB 를 넘으면 스트림에서 끊는다 — 50 MiB 본문
    big = b"0\nLINE\n" * (50 * MiB // 7)
    t0 = time.perf_counter()
    r = tc.post(url, headers=op, files={"file": ("big.dxf", big, "application/dxf")})
    rec("G2-E01", "업로드 50 MiB", r.status_code == 413, {"status": r.status_code, "body": r.json(), "sec": round(time.perf_counter() - t0, 2)})

    # 3. 바이너리 · 압축 · 아카이브 · 깨짐
    gz = gzip.compress(sample)
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.dxf", b"0\nLINE\n" * 2_000_000)                      # 14 MB → 압축 폭탄 꼴
    cases = {
        "바이너리 DXF 표지": b"AutoCAD Binary DXF\r\n\x1a\x00" + b"\x00" * 100,
        "gzip(.dxf 이름)": gz,
        "zip 폭탄(.dxf 이름)": zb.getvalue(),
        "빈 파일": b"",
        "홀수 줄": b"0\nSECTION\n2\n",
        "SECTION 없음": b"999\nhello\n",
        "그룹 코드 문자": b"X\nY\n",
        "닫히지 않은 SECTION": b"0\nSECTION\n2\nENTITIES\n0\nLINE\n",
        "중첩 SECTION": b"0\nSECTION\n2\nENTITIES\n0\nSECTION\n2\nX\n0\nENDSEC\n0\nENDSEC\n0\nEOF\n",
        "UTF-16": "0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n".encode("utf-16"),
    }
    for label, raw in cases.items():
        s, b, dt, _ = up(raw)
        rec("G2-E01", f"깨진 문서 · {label}", s == 422 and err(b)[0] == "invalid_document", {"status": s, "err": err(b)}, "422 invalid_document")
    zsize = len(zb.getvalue())

    # 4. 좌표 — NaN · inf · 1e309 · 거대 유한 · 정수 코드 문자
    for label, val in (("nan", "nan"), ("inf", "inf"), ("-inf", "-Infinity"), ("1e309", "1e309"), ("1e308", "1e308"),
                       ("1e9", "1e9"), ("1e-320", "1e-320")):
        raw = dxf([(0, "LINE"), (8, "L"), (10, val), (20, "0"), (11, "1"), (21, "1")] + text("x", 1, 1))
        s, b, dt, _ = up(raw)
        want = 201 if label == "1e-320" else 422
        rec("G2-E01", f"좌표 {label}", s == want, {"status": s, "err": err(b)}, want)
    raw = dxf(circle(0, 0, "1e300") + text("x", 1, 1))
    s, b, dt, _ = up(raw)
    rec("G2-E01", "원 반지름 1e300", s == 422, {"status": s, "err": err(b)}, 422)
    raw = dxf([(0, "LWPOLYLINE"), (8, "L"), (90, "4"), (70, "abc")] + text("x", 1, 1))
    s, b, dt, _ = up(raw)
    rec("G2-E01", "정수 코드 70 = 'abc'", s == 422, {"status": s, "err": err(b)}, 422)
    # LWPOLYLINE 꼭짓점 4,001(상한 4,000)
    ents = [(0, "LWPOLYLINE"), (8, "L"), (90, "4001"), (70, "0")]
    for i in range(4001):
        ents += [(10, str(i)), (20, "0")]
    s, b, dt, _ = up(dxf(ents))
    rec("G2-E01", "꼭짓점 4,001", s == 413 and err(b) == ("document_too_large", "vertices"), {"status": s, "err": err(b)}, "413 vertices")

    # 5. 악성 텍스트 — 스크립트 · 수식 · 제어문자 · NUL(4096 바이트 뒤) · 긴 레이어 · \U+ 표기
    nasty = ["<script>alert(1)</script>", "=HYPERLINK(\"x\",\"y\")", "+1+1", "@SUM(1)", "-1+1", "\\U+0000NUL", "A\x07B",
             "\\U+202Egnp.exe", "'; DROP TABLE mlp_quote; --"]
    ents = rect(0, 0, 200, 200, "BOM") + text("BILL OF MATERIALS", 5, 190, "BOM")
    for i, v in enumerate(nasty):
        ents += text(f"{v} | M1 | 1 | 10", 5, 180 - i * 10, "BOM")
    s, b, dt, _ = up(dxf(ents))
    texts = [t_ for r in (b.get("regions") or []) for t_ in r.get("texts", [])]
    rec("G2-E01", "악성 텍스트(스크립트 · 수식 · \\U+0000 · 제어문자)", s in (201, 422) and s != 500,
        {"status": s, "err": err(b), "texts_has_nul": any("\x00" in x for x in texts), "n_texts": len(texts)}, "201(원문 저장 · 렌더 시 이스케이프) 또는 422 — 500 아님")
    pad = "999\n" + "y" * 5000 + "\n"
    raw = (pad + dxf(text("BOM\x00X", 1, 1) + rect(0, 0, 5, 5)).decode()).encode()
    s, b, dt, _ = up(raw)
    rec("G2-E01", "NUL 문자(앞 4096 바이트 뒤) 텍스트", s in (201, 422), {"status": s, "err": err(b), "body": str(b)[:160]}, "201 또는 422 — 500 아님")
    raw = dxf([(0, "LINE"), (8, "L" * 2_000_000), (10, "0"), (20, "0"), (11, "1"), (21, "1")] + text("x", 1, 1))
    s, b, dt, size = up(raw)
    rec("G2-E01", "레이어 이름 2,000,000자", s in (201, 422, 413), {"status": s, "err": err(b), "resp_bytes": size, "sec": round(dt, 2)})
    raw = dxf(text("Q" * 3_000_000, 1, 1) + rect(0, 0, 5, 5))
    s, b, dt, size = up(raw)
    rec("G2-E01", "텍스트 3,000,000자(TEXT_MAX 2,000 자름)", s == 201 and size < 100_000, {"status": s, "resp_bytes": size})

    # 6. 경로 같은 파일 이름
    names = {"../../../etc/passwd.dxf": "passwd.dxf", "..\\..\\win.dxf": "win.dxf", "C:\\x\\y.dxf": "y.dxf",
             "/abs/path/z.dxf": "z.dxf", "a" * 400 + ".dxf": None, "\u202egpj.dxf": None, "x.DXF": "x.DXF",
             "noext": "422", ".dxf": None, "a.dxf\x00.exe": None, "a.dxf/": "422"}
    for nm, want in names.items():
        s, b, dt, _ = up(sample, nm)
        got = b.get("filename") if s == 201 else str(s)
        ok = (want == "422" and s == 422) or (s == 201 and "/" not in got and "\\" not in got and len(got) <= 150
                                               and (want is None or got == want))
        rec("G2-E01", f"파일 이름 {nm[:40]!r}", ok, {"status": s, "filename": got if s == 201 else err(b), "len": len(got)})
    with h.connect() as c:
        paths = [r["raw_path"] for r in c.execute("SELECT raw_path FROM mlp_document WHERE tenant_id=%s", (t,)).fetchall()]
    rec("G2-E01", "원본 저장 경로 = <tenant>/<sha256>.dxf 만", all(p.endswith(".dxf") and "/" + t + "/" in "/" + p and ".." not in p for p in paths),
        {"n": len(paths), "sample": paths[:2]})

    # 7. 단위 · unit_override
    raw = dxf(text("x", 1, 1), insunits=None)
    for unit, want in ((None, 422), ("mm", 201), ("inch", 201), ("m", 422), ("../mm", 422), ("MM", 422)):
        s, b, dt, _ = up(raw, unit=unit)
        rec("G2-E01", f"unit_override={unit}", s == want, {"status": s, "err": err(b)}, want)

    # 8. multipart 꼴 공격 — boundary 없음 · file 칸 둘 · 다른 칸 이름 · base64 전송 인코딩
    r = tc.post(url, headers={**op, "Content-Type": "multipart/form-data"}, content=b"x")
    rec("G2-E01", "multipart boundary 없음", r.status_code == 422, {"status": r.status_code})
    r = tc.post(url, headers={**op, "Content-Type": "application/json"}, content=b"{}")
    rec("G2-E01", "JSON 본문", r.status_code == 422, {"status": r.status_code})
    r = tc.post(url, headers=op, files=[("file", ("a.dxf", sample, "application/dxf")), ("file", ("b.dxf", b"junk", "x"))])
    rec("G2-E01", "file 칸 2개(첫째 사용)", r.status_code == 201, {"status": r.status_code})
    import base64
    bnd = "QA22BND"
    body = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.dxf\"\r\n"
            f"Content-Transfer-Encoding: base64\r\nContent-Type: application/dxf\r\n\r\n").encode() + base64.b64encode(sample) + \
        f"\r\n--{bnd}--\r\n".encode()
    r = tc.post(url, headers={**op, "Content-Type": f"multipart/form-data; boundary={bnd}"}, content=body)
    rec("G2-E01", "base64 전송 인코딩 칸", r.status_code in (201, 422), {"status": r.status_code})
    r = tc.post(url, headers={**op, "Content-Encoding": "gzip"}, files={"file": ("a.dxf", sample, "application/dxf")})
    rec("G2-E01", "Content-Encoding: gzip 머리(압축 해제 안 함)", r.status_code in (201, 422), {"status": r.status_code})

    # 9. 역할 · 회사 범위 · 감사
    a0 = count("mlp_audit", "tenant_id=%s AND action LIKE %s", (t, "POST /api/v1/tenants/{t}/tasks/{task}/documents%"))
    s, b, dt, _ = up(sample, key=h.hdr(k["viewer"]))
    rec("G2-A01", "viewer 업로드", s == 403, {"status": s})
    s, b, dt, _ = up(sample)
    a1 = count("mlp_audit", "tenant_id=%s AND action LIKE %s", (t, "POST /api/v1/tenants/{t}/tasks/{task}/documents%"))
    rec("감사", "문서 업로드 2회(403 · 201) → mlp_audit +2", a1 - a0 == 2, {"delta": a1 - a0})
    with h.connect() as c:
        last = c.execute("SELECT actor, detail, target FROM mlp_audit WHERE tenant_id=%s AND action LIKE %s ORDER BY ts DESC LIMIT 1",
                         (t, "POST %documents%")).fetchone()
    rec("감사", "업로드 감사 행 내용(문서 ID 남김?)", "doc_" in json.dumps(last["detail"], default=str), {"row": dict(last)},
        "doc_id 또는 sha256 이 감사에 남는다 (누가 어떤 도면을 올렸는지 추적)")
    doc_id = b.get("doc_id")

    m2 = h.make_tenant("kd", base / "other")
    k2 = h.keys(m2)
    t2 = m2.tenant.code
    for label, path in (("GET 문서", f"/api/v1/tenants/{t}/tasks/{t}.drawing_regions/documents/{doc_id}"),
                        ("GET 목록", f"/api/v1/tenants/{t}/tasks/{t}.drawing_regions/documents"),
                        ("GET 다른 회사 경로로 내 문서", f"/api/v1/tenants/{t2}/tasks/{t2}.drawing_regions/documents/{doc_id}")):
        r = tc.get(path, headers=h.hdr(k2["admin"]))
        rec("G2-A01", f"다른 회사 admin 키 · {label}", r.status_code == 404, {"status": r.status_code, "code": (r.json().get("error") or {}).get("code")})
    r = tc.post(f"/api/v1/tenants/{t}/tasks/{t}.drawing_regions/documents", headers=h.hdr(k2["admin"]),
                files={"file": ("a.dxf", sample, "application/dxf")})
    rec("G2-A01", "다른 회사 키 업로드", r.status_code == 404, {"status": r.status_code})
    r = tc.get(f"/api/v1/tenants/{t}/tasks/{t}.labor_hours/documents", headers=op)
    rec("G2-A01", "extract 아닌 과제의 documents → 404 type_route", r.status_code == 404 and err(r.json())[1] == "type_route", {"status": r.status_code, "err": err(r.json())})

    # 10. CPU · 메모리 — 상한 안의 최악 꼴 (cad_regions 키워드 텍스트 N × 사각형 N, bom_text 가 같은 분석을 한 번 더)
    regions = load("packs/eto/extractors/cad_regions.py", "qa22_cad_regions")
    scaling = []
    for n in (250, 500, 1000, 2000):
        ents = []
        for i in range(n):
            ents += rect(-i - 1, -i - 1, 2 * i + 2, 2 * i + 2, "BOM")      # 중첩 사각형 n 개(모두 원점을 감싼다)
        for i in range(n):
            ents += text("BOM", i + 0.5, 0, "BOM")
        raw = dxf(ents)
        tracemalloc.start()
        t0 = time.perf_counter()
        res = regions.extract(raw, "x.dxf", unit="mm", limits={"max_entities": 20000})
        dt = time.perf_counter() - t0
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        out_bytes = len(json.dumps(res["regions"], ensure_ascii=False))
        scaling.append({"n_rect": n, "n_text": n, "entities": 2 * n, "file_bytes": len(raw), "sec": round(dt, 2),
                        "peak_MB": round(peak / MiB, 1), "regions": len(res["regions"]), "regions_json_MB": round(out_bytes / MiB, 2)})
    proj = scaling[-1]
    f = (10000 / proj["n_rect"]) ** 2
    rec("G2-E01", "cad_regions 최악 꼴 규모(키워드 텍스트 × 중첩 사각형)", "WARN" if proj["sec"] < 5 else False,
        {"scaling": scaling, "projection_20000_entities": {"sec_x1": round(proj["sec"] * f, 0), "regions_json_MB": round(proj["regions_json_MB"] * f, 0),
                                                           "note": "bom_text 가 analyze 를 한 번 더 부른다(×2)"}},
        "상한(20,000 · 5 MiB) 안의 문서 1건이 수 초 안에 끝나고 응답 · 저장 크기가 유한")
    # API 로 n=2000 한 번(실측)
    ents = []
    for i in range(2000):
        ents += rect(-i - 1, -i - 1, 2 * i + 2, 2 * i + 2, "BOM")
    for i in range(2000):
        ents += text("BOM", i + 0.5, 0, "BOM")
    s, b, dt, size = up(dxf(ents))
    rec("G2-E01", "API 업로드 · 사각형 2,000 + 키워드 텍스트 2,000 (엔티티 4,000 · 상한의 20%)", dt < 10 and size < 5 * MiB,
        {"status": s, "sec": round(dt, 1), "resp_MB": round(size / MiB, 1)}, "< 10 s · 응답 < 5 MiB")

    # 10b. ot geometry_objects — 꼭짓점 500 × bulge 외곽 + 원 다수(점 상한 60,000 안), contains O(점 × 외곽 꼭짓점)
    geo = load("packs/rollform-quote/extractors/geometry_objects.py", "qa22_geo")
    params = {"max_vertices": 500, "flatten_mm": 0.2, "flatten_segments": 8, "max_points_entity": 2000, "max_points": 60000,
              "coord_limit": 10000000, "aspect_cap": 1000}
    import math
    ents = [(0, "LWPOLYLINE"), (8, "O"), (90, "500"), (70, "1")]
    for i in range(500):
        a = 2 * math.pi * i / 500
        ents += [(10, repr(5000 * math.cos(a))), (20, repr(5000 * math.sin(a))), (42, "0.3")]
    n_c = 0
    for i in range(1999):
        ents += circle(-3000 + (i % 60) * 100, -3000 + (i // 60) * 100, 20)
        n_c += 1
    raw = dxf(ents)
    t0 = time.perf_counter()
    try:
        res = geo.extract(raw, "x.dxf", unit="mm", limits={"max_entities": 2000}, context={"params": params})
        out = {"objects": len(res["objects"]), "outer_pts": max(len(o["points"]) for o in res["objects"])}
    except Exception as e:  # noqa: BLE001
        out = {"error": f"{type(e).__name__}: {getattr(e, 'rule', '')} {e}"[:200]}
    dt = time.perf_counter() - t0
    rec("G2-E01", "ot geometry_objects 최악 꼴(외곽 bulge 500 + 원 1,999)", "WARN" if dt < 10 else False,
        {**out, "sec": round(dt, 1), "file_bytes": len(raw)}, "< 10 s")

    save("probe_dxf-result.json")
    print(json.dumps({"tenant": t, "zip_bytes": zsize}))


if __name__ == "__main__":
    main()
