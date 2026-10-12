"""규칙 추출기 — 평면 DXF 전개도의 2D 도형 · 기하 설명자 · 외곽 · 치수 (task-contract §6.2 · source_inventory §10.5 X1~X10).

원천 `api/cad.py:38-137 analyze()` 를 **읽어** 이관했다(실행하지 않는다). 원천은 ezdxf 로 읽고 `make_path(e).flattening(0.2/scale, 8)`
로 곡선을 점열로 바꾼다. 표준은 코어 DXF 읽개 `mlcore.tasks.dxf.read`(그룹 코드 쌍, 외부 의존 0)를 쓰고, 곡선 → 3차 베지어 →
적응 분할 점열은 원천이 쓰는 ezdxf 1.4 의 계산 순서(원 · 호 = 90° 이하 베지어 · bulge = 호 하나, 중점 거리 < 0.2 mm 까지 이분)를
같은 부동소수 연산 순서로 다시 썼다 — 같은 도면에서 같은 점 · 면적 · 둘레(소수 3 · 4 자리)가 나오는지는
`tests/test_rollform_quote_pack.py` 가 원천 앱이 저장한 분석 결과(읽기 전용 사본 fixture)로 본다.

규칙(원천 그대로, 상한 · 허용차는 과제 extractors[].params — 코드 상수 0):
  X3 요소 상한은 코어(과제 document.max_entities 2,000).  X2 단위는 코어가 정한 원본 단위(`unit`) → mm.
  X4 지원 요소 LINE · CIRCLE · ARC · LWPOLYLINE, 그 밖은 skipped 집계.  X5 비평면(extrusion ≠ (0,0,1) · |Z| > 0.001 mm) 제외.
  X6 폴리라인 꼭짓점 ≤ max_vertices · 평탄화 flatten_mm · 요소당 ≤ max_points_entity 점 · 전체 ≤ max_points 점 · |좌표| ≤ coord_limit.
  X7 객체 = 면적 · 둘레 · bbox · 폭 · 높이, 외곽 = 가장 큰 폐합 LWPOLYLINE.  X8 설명자 6(분류는 다음 추출기 object_classifier).
  X9 기하 검증 8 사유 중 모델과 무관한 앞 3 개(열린 도형 · 외곽 없음 · 외곽 밖/교차)는 여기서, 나머지 5 개는 분류 뒤 모델 추출기가.
  X10 dimensions{length, width} = 외곽 bbox 긴 변 · 짧은 변 · 경고 문구.
이 추출기의 objects 는 분류 전(label other · model_label null · confidence null) — 모델 추출기가 같은 객체를 분류해 바꾼다(replaces).
"""

from __future__ import annotations

import math
from collections import Counter

from mlcore.tasks.dxf import SCALE_TO_MM, read
from mlcore.tasks.extract import ExtractError

NAME = "geometry_objects"
VERSION = "1.0.0"
KIND = "rule"

SUPPORTED = ("LINE", "CIRCLE", "ARC", "LWPOLYLINE")
DEFAULTS = {"max_vertices": 500, "flatten_mm": 0.2, "flatten_segments": 8, "max_points_entity": 2000, "max_points": 60000,
            "coord_limit": 1e7, "aspect_cap": 1000}
DESCRIPTORS = ("is_circle", "is_closed", "aspect_ratio", "area_ratio", "circularity", "is_curved")
WARN_BASE = ("XY 축에 정렬된 단일 부품의 1:1 전개도 기준입니다. 치수 문자·투상도에서 길이·전개 폭·두께·굽힘 수를 해석하지 않습니다.",
             "객체 점수는 합성 기하 분류 모델의 점수이며, 실제 도면의 보정된 신뢰확률이 아닙니다.")
REASON_OPEN = "열린 도형: 폐곡선 연결 및 용도 확인 필요"
REASON_NO_OUTER = "기준 외곽 폐곡선 없음"
REASON_OUTSIDE = "외곽 밖 또는 교차 도형: 단일 전개도 확인 필요"
PENDING = "모델 분류 전"

_TAU = math.tau
_REL, _ABS = 1e-9, 1e-12               # ezdxf Vec3.isclose 기본 허용차
_IS_CLOSE_TOL = 1e-10                  # ezdxf path.tools.IS_CLOSE_TOL
_RAD_ABS_TOL = 1e-15


# ── 작은 벡터 (x, y, z) — ezdxf Vec3 와 같은 성분별 연산 순서 ──────────────────────────────────
def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, f):
    return (a[0] * f, a[1] * f, a[2] * f)


def _mag(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _normalize(a, length=1.0):
    f = length / _mag(a)
    return (a[0] * f, a[1] * f, a[2] * f)


def _close1(a, b, rel, abs_):
    diff = abs(b - a)
    return diff <= abs(rel * b) or diff <= abs(rel * a) or diff <= abs_


def _isclose(a, b, rel=_REL, abs_=_ABS):
    return _close1(a[0], b[0], rel, abs_) and _close1(a[1], b[1], rel, abs_) and _close1(a[2], b[2], rel, abs_)


def _dist(a, b):
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


# ── 3차 베지어 · 적응 분할 (ezdxf acc/bezier4p.pyx Bezier4P.flattening · _Flattening) ───────────
def _bezier_flatten(cp, distance: float, segments: int) -> list:
    p0, p1, p2, p3 = cp
    off = p0
    q1 = (p1[0] - off[0], p1[1] - off[1], p1[2] - off[2])
    q2 = (p2[0] - off[0], p2[1] - off[1], p2[2] - off[2])
    q3 = (p3[0] - off[0], p3[1] - off[1], p3[2] - off[2])

    def point(t):
        t2 = t * t
        u = 1.0 - t
        b, c, d = 3.0 * u * u * t, 3.0 * u * t2, t2 * t
        x = 0.0 + q1[0] * b
        y = 0.0 + q1[1] * b
        z = 0.0 + q1[2] * b
        x += q2[0] * c
        y += q2[1] * c
        z += q2[2] * c
        x += q3[0] * d
        y += q3[1] * d
        z += q3[2] * d
        return (x + off[0], y + off[1], z + off[2])

    out = [p0]

    def flatten(sp, ep, st, et, level=0):
        if level > 1000:
            raise ExtractError("document_too_large", "points", "곡선이 너무 복잡합니다. 도면을 단순화하세요.")
        mid_t = (st + et) * 0.5
        mp = point(mid_t)
        chk = (sp[0] + (ep[0] - sp[0]) * 0.5, sp[1] + (ep[1] - sp[1]) * 0.5, sp[2] + (ep[2] - sp[2]) * 0.5)
        if _dist(mp, chk) < distance:
            out.append(ep)
        else:
            flatten(sp, mp, st, mid_t, level + 1)
            flatten(mp, ep, mid_t, et, level + 1)

    dt = 1.0 / segments
    t0, sp = 0.0, p0
    while t0 < 1.0:
        t1 = t0 + dt
        if _close1(t1, 1.0, _REL, _ABS):
            ep, t1 = p3, 1.0
        else:
            ep = point(t1)
        flatten(sp, ep, t0, t1)
        t0, sp = t1, ep
    return out


def _arc_params(start: float, end: float):
    """ezdxf cubic_bezier_arc_parameters(start, end, segments=1) — 단위원 위 (시작, 제어1, 제어2, 끝)."""
    delta = end - start
    if not delta > 0:
        raise ValueError("호 각도 폭이 0")
    count = max(int(math.ceil(delta / math.pi * 2.0)), 1)
    seg = delta / count
    tl = (4.0 / 3.0) * math.tan(seg / 4.0)
    angle = start
    e = (math.cos(angle) * 1.0, math.sin(angle) * 1.0, 0.0)
    for _ in range(count):
        s = e
        angle += seg
        e = (math.cos(angle) * 1.0, math.sin(angle) * 1.0, 0.0)
        c1 = (s[0] - s[1] * tl, s[1] + s[0] * tl, 0.0)
        c2 = (e[0] + e[1] * tl, e[1] - e[0] * tl, 0.0)
        yield s, c1, c2, e


def _span_rad(start: float, end: float) -> float:
    """ezdxf arc_angle_span_rad."""
    if _close1(start, end, _REL, _RAD_ABS_TOL):
        return 0.0
    start %= _TAU
    if _close1(start, end % _TAU, _REL, _RAD_ABS_TOL):
        return _TAU
    if not _close1(end, _TAU, _REL, _RAD_ABS_TOL):
        end %= _TAU
    if end < start:
        end += _TAU
    return end - start


def _norm_rad(a: float) -> float:
    r = math.fmod(a, _TAU)
    return r + _TAU if r < 0.0 else r


class _Ellipse:
    """ezdxf ConstructionEllipse.from_arc(center, radius, Z, start°, end°) — 원 · 호(ratio 1, 축 = OCS x)."""

    def __init__(self, center, radius: float, start_deg: float, end_deg: float):
        self.center = (float(center[0]), float(center[1]), float(center[2]) if len(center) > 2 else 0.0)
        self.major = (abs(radius), 0.0, 0.0)
        z = (0.0, 0.0, 1.0)
        cross = (z[1] * self.major[2] - z[2] * self.major[1], z[2] * self.major[0] - z[0] * self.major[2],
                 z[0] * self.major[1] - z[1] * self.major[0])
        self.minor = _normalize(cross, _mag(self.major) * 1.0)
        self.start = math.radians(start_deg)
        self.end = math.radians(end_deg)

    def span(self) -> float:
        return _span_rad(self.start, self.end)

    def start_point(self):
        x_axis, y_axis = _normalize(self.major), _normalize(self.minor)
        rx = _mag(self.major)
        ry = rx * 1.0
        x = _mul(x_axis, math.cos(self.start) * rx)
        y = _mul(y_axis, math.sin(self.start) * ry)
        return _add(_add(self.center, x), y)

    def beziers(self) -> list:
        span = self.span()
        if abs(span) < 1e-9:
            return []
        s = _norm_rad(self.start)
        e = s + span
        while s > e:
            e += _TAU
        out = []
        for cps in _arc_params(s, e):
            out.append(tuple((self.center[0] + self.major[0] * c[0] + self.minor[0] * c[1],
                              self.center[1] + self.major[1] * c[0] + self.minor[1] * c[1],
                              self.center[2] + self.major[2] * c[0] + self.minor[2] * c[1]) for c in cps))
        return out


def _reverse(curves: list) -> list:
    return [(c[3], c[2], c[1], c[0]) for c in reversed(curves)]


class _Path:
    """ezdxf Path 의 LINE_TO · CURVE4_TO 만."""

    def __init__(self, start=None):
        self.start = start
        self.cmds: list = []

    @property
    def end(self):
        return self.cmds[-1][-1] if self.cmds else self.start

    def line_to(self, p):
        self.cmds.append(("L", p))

    def add_beziers(self, curves: list):          # ezdxf path.tools.add_bezier4p
        if not curves:
            return
        if _isclose(self.end, curves[-1][3]):
            curves = _reverse(curves)
        for c in curves:
            s, c1, c2, e = c
            if not _isclose(s, self.end):
                self.line_to(s)
            if _isclose(s, c1, 1e-15, 0.0) and _isclose(e, c2, 1e-15, 0.0):
                self.line_to(e)
            else:
                self.cmds.append(("C", c1, c2, e))

    def flatten(self, distance: float, segments: int) -> list:
        if not self.cmds:
            return []
        out = [self.start]
        cur = self.start
        for cmd in self.cmds:
            if cmd[0] == "L":
                out.append(cmd[1])
            else:
                out.extend(_bezier_flatten((cur, cmd[1], cmd[2], cmd[3]), distance, segments)[1:])
            cur = cmd[-1]
        return out


def _ellipse_path(center, radius, start_deg, end_deg) -> _Path:
    p = _Path()
    if abs(radius) <= 1e-12:
        return p
    el = _Ellipse(center, radius, start_deg, end_deg)
    if abs(el.span()) < 1e-9:
        return p
    p.start = el.start_point()
    p.add_beziers(el.beziers())
    return p


def _bulge_to(path: _Path, p1, p2, bulge: float):
    """ezdxf add_2d_polyline.bulge_to (segments 1 → 베지어 1 묶음) · bulge_to_arc."""
    if _isclose(p1, p2, _IS_CLOSE_TOL, 0.0):
        return
    dist = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
    r = dist * (1.0 + bulge * bulge) / 4.0 / bulge
    a = math.atan2(p2[1] - p1[1], p2[0] - p1[0]) + (math.pi / 2 - math.atan(bulge) * 2)
    c = (p1[0] + math.cos(a) * r, p1[1] + math.sin(a) * r)
    ang = lambda q: math.atan2(q[1] - c[1], q[0] - c[0])   # noqa: E731
    sa, ea = (ang(p2), ang(p1)) if bulge < 0 else (ang(p1), ang(p2))
    sa, ea = sa % _TAU, ea % _TAU
    if sa > ea:
        ea += _TAU
    el = _Ellipse((c[0], c[1], 0.0), abs(r), math.degrees(sa), math.degrees(ea))
    curves = el.beziers()
    if _isclose(curves[0][0], p2, _IS_CLOSE_TOL, 0.0):
        curves = _reverse(curves)
    path.add_beziers(curves)


def _lw_points(ent) -> list[tuple[float, float, float]]:
    out: list[list[float]] = []
    for code, value in ent.codes:
        if code == 10:
            out.append([float(value), 0.0, 0.0])
        elif code == 20 and out:
            out[-1][1] = float(value)
        elif code == 42 and out:
            out[-1][2] = float(value)
    return [(x, y, b) for x, y, b in out]


def _lw_path(points, closed: bool) -> _Path:
    path = _Path()
    prev, prev_b = None, 0.0
    for x, y, b in points:
        if abs(b) < 1e-6:
            b = 0.0
        pt = (x, y, 0.0)
        if prev is None:
            path.start, prev, prev_b = pt, pt, b
            continue
        if prev_b:
            _bulge_to(path, prev, pt, prev_b)
        else:
            path.line_to(pt)
        prev, prev_b = pt, b
    if path.start is not None and closed and not _isclose(path.start, path.end, _IS_CLOSE_TOL, 0.0):
        if prev_b:
            _bulge_to(path, path.end, path.start, prev_b)
        else:
            path.line_to(path.start)
    return path


def _extrusion(ent) -> tuple[float, float, float]:
    return (ent.num(210, 0.0), ent.num(220, 0.0), ent.num(230, 1.0))


def polygon_area(points) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2


def contains(point, polygon) -> bool:
    x, y = point
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def _params(context: dict | None) -> dict:
    p = dict(DEFAULTS)
    p.update((context or {}).get("params") or {})
    return p


def extract(raw: bytes, filename: str, *, unit: str, limits: dict, model=None, context: dict | None = None) -> dict:
    prm = _params(context)
    doc = read(raw, max_entities=int(limits.get("max_entities") or 20000))
    if unit not in SCALE_TO_MM:
        raise ExtractError("invalid_document", "unit", "지원하지 않는 DXF 단위입니다. mm 단위로 변환하세요.")
    scale = SCALE_TO_MM[unit]
    distance = float(prm["flatten_mm"]) / scale
    segments = int(prm["flatten_segments"])
    objects, skipped = [], Counter()
    total_points = 0
    for ent in doc.entities:
        kind = ent.type
        if kind not in SUPPORTED:
            skipped[kind] += 1
            continue
        if _extrusion(ent) != (0.0, 0.0, 1.0):
            skipped["비평면/뒤집힌 OCS"] += 1
            continue
        closed, curved = kind == "CIRCLE", kind in ("CIRCLE", "ARC")
        lw = None
        if kind == "LWPOLYLINE":
            lw = _lw_points(ent)
            if len(lw) > int(prm["max_vertices"]):
                raise ExtractError("document_too_large", "vertices",
                                   f"폴리라인 꼭짓점은 {int(prm['max_vertices'])}개 이하로 줄여주세요.")
            closed = bool(int(ent.num(70, 0) or 0) & 1)
            curved = any(abs(b) > 1e-9 for _, _, b in lw)
        try:
            if kind == "LINE":
                vertices = [(ent.num(10, 0.0), ent.num(20, 0.0), ent.num(30, 0.0)),
                            (ent.num(11, 0.0), ent.num(21, 0.0), ent.num(31, 0.0))]
            else:
                if kind == "LWPOLYLINE":
                    path = _lw_path(lw, closed)
                    elev = ent.num(38, 0.0) or 0.0
                else:
                    center = (ent.num(10, 0.0), ent.num(20, 0.0), ent.num(30, 0.0))
                    a0, a1 = (ent.num(50, 0.0), ent.num(51, 360.0)) if kind == "ARC" else (0.0, 360.0)
                    path = _ellipse_path(center, abs(ent.num(40, 0.0)), a0, a1)
                    elev = 0.0
                vertices = []
                for v in path.flatten(distance, segments):
                    vertices.append((v[0], v[1], v[2] + elev if elev else v[2]))
                    if len(vertices) > int(prm["max_points_entity"]):
                        raise ExtractError("document_too_large", "points", "곡선이 너무 복잡합니다. 도면을 단순화하세요.")
            if any(abs(v[2] * scale) > .001 for v in vertices):
                skipped["비평면 Z 좌표"] += 1
                continue
            points = [[float(v[0] * scale), float(v[1] * scale)] for v in vertices]
            if any(not math.isfinite(c) or abs(c) > float(prm["coord_limit"]) for p in points for c in p):
                raise ExtractError("invalid_document", "parse", "유효하지 않거나 너무 큰 도면 좌표입니다.")
            if len(points) < 2:
                continue
            total_points += len(points)
            if total_points > int(prm["max_points"]):
                raise ExtractError("document_too_large", "points", "전체 곡선 점 수가 너무 많습니다. 도면을 단순화하세요.")
            if points[0] == points[-1]:
                points = points[:-1]
            if len(points) < 2:
                continue
            area = polygon_area(points) if closed else 0
            perimeter = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
            if closed:
                perimeter += math.dist(points[-1], points[0])
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            if max(w, h) < 1e-8:
                continue
            objects.append({"id": f"OBJ-{len(objects) + 1:03}", "entity": kind, "layer": str(ent.layer), "points": points,
                            "closed": closed, "curved": bool(curved), "area": area, "perimeter": perimeter, "bbox": bbox,
                            "width": w, "height": h})
        except ExtractError:
            raise
        except Exception:                      # noqa: BLE001 — 원천과 같이 해석 실패 요소는 공개 집계
            skipped[kind + " 해석 실패"] += 1
    if not objects:
        raise ExtractError("invalid_document", "parse",
                           "해석 가능한 2D 도형이 없습니다. 블록을 분해한 XY 평면 DXF 전개도를 사용하세요.")
    polys = [o for o in objects if o["closed"] and o["entity"] == "LWPOLYLINE" and o["area"] > 0]
    outer = max(polys, key=lambda o: o["area"]) if polys else None
    largest = outer["area"] if outer else max(o["area"] for o in objects) or 1
    cap = float(prm["aspect_cap"])
    for o in objects:
        o["descriptors"] = dict(zip(DESCRIPTORS, (
            int(o["entity"] == "CIRCLE"), int(o["closed"]),
            min(cap, max(o["width"], o["height"]) / max(.001, min(o["width"], o["height"]))),
            o["area"] / largest, 4 * math.pi * o["area"] / max(.001, o["perimeter"] ** 2), int(o["curved"]))))
    for o in objects:          # 원천 순서 그대로 — 사유 판정 뒤 그 객체의 점을 반올림한다(외곽이 앞이면 반올림된 외곽 점으로 포함 판정)
        reason = None
        if not o["closed"]:
            reason = REASON_OPEN
        elif not outer:
            reason = REASON_NO_OUTER
        elif o is not outer and not all(contains(p, outer["points"]) for p in o["points"]):
            reason = REASON_OUTSIDE
        o.update({"is_outer": o is outer, "geometry_reason": reason, "model_label": None, "confidence": None,
                  "label": "other", "review_reason": reason or PENDING})
        for k in ("area", "perimeter", "width", "height"):
            o[k] = round(o[k], 3)
        o["points"] = [[round(v, 4) for v in p] for p in o["points"]]
    bbox = [min(o["bbox"][0] for o in objects), min(o["bbox"][1] for o in objects),
            max(o["bbox"][2] for o in objects), max(o["bbox"][3] for o in objects)]
    warnings = list(WARN_BASE)
    if skipped:
        warnings.append("제외 도형: " + ", ".join(f"{k} {v}개" for k, v in sorted(skipped.items())) + ". 누락 항목을 확인하세요.")
    if not outer:
        warnings.append("외곽을 찾지 못해 치수 자동 입력이 불가능합니다.")
    if doc.insunits() in (None, 0) and (limits or {}).get("unit_override"):
        warnings.append(f"도면 단위 미지정: 사용자가 선택한 {unit}를 적용했습니다.")
    dims = ({"length": round(max(outer["width"], outer["height"]), 3), "width": round(min(outer["width"], outer["height"]), 3)}
            if outer else None)
    return {"objects": objects, "regions": [], "bom_rows": [], "counts": {}, "dimensions": dims, "confidence": None,
            "unit": "mm", "source_unit": unit, "bbox": bbox, "skipped": dict(skipped), "entity_count": doc.entity_count,
            "warnings": warnings}
