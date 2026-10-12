"""ASCII DXF 읽개 — 그룹 코드 쌍만 읽는다(외부 의존 0, 네트워크 0). 소유 개발2 (progress-dev2 2차 §1.1).

코어가 업로드를 받을 때 한 번 읽어 형식 · 바이너리 · 파싱 · 엔티티 수 · 단위를 판정하고(task-contract §6.2 ·
api-contract §6.1), 추출기 플러그인도 같은 함수를 쓸 수 있다. 도면의 뜻(영역 · 객체 · BOM)은 모른다 — 그건 팩 추출기.

- 해독 순서: UTF-8-sig → cp949 → cp1252 (migration/source_inventory.md §10.5 X1 · §11.5 R1).
- 바이너리 DXF(`AutoCAD Binary DXF`) 거부 → rule `binary`.
- 그룹 코드는 정수, 좌표 · 실수 코드(10~59 · 110~149 · 210~239 · 1010~1059)는 유한 실수 — 아니면 rule `parse`.
- 엔티티 수 = ENTITIES 구간의 `0 <형식>` 레코드(하위 레코드 VERTEX · SEQEND · ATTRIB 제외, 종이 공간 `67 1` 제외).
  `max_entities` 를 넘는 순간 멈추고 `document_too_large`(rule `entities`).
- 단위: 헤더 `$INSUNITS` 1 inch · 4 mm · 5 cm · 6 m. 0 · 그 밖 · 없음이면 `unit_override`(mm · inch) — 둘 다 없으면 rule `unit`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["DxfDoc", "Entity", "read", "resolve_unit", "SCALE_TO_MM", "INSUNITS", "DocumentError"]

BINARY_SENTINEL = b"AutoCAD Binary DXF"
ENCODINGS = ("utf-8-sig", "cp949", "cp1252")
INSUNITS = {1: "inch", 4: "mm", 5: "cm", 6: "m"}
SCALE_TO_MM = {"mm": 1.0, "inch": 25.4, "cm": 10.0, "m": 1000.0}
OVERRIDES = ("mm", "inch")
SUBRECORDS = {"VERTEX", "SEQEND", "ATTRIB"}
TEXT_MAX = 2000                 # 텍스트 값 최대 길이 — 넘으면 자른다(source_inventory §11.5 R4)


class DocumentError(ValueError):
    """문서 판정 오류 — code = invalid_document(422) | document_too_large(413), rule = api-contract §6.1."""

    def __init__(self, code: str, rule: str, message: str = ""):
        super().__init__(message or f"{code}:{rule}")
        self.code, self.rule, self.message = code, rule, message or code


def _float_code(code: int) -> bool:
    return 10 <= code <= 59 or 110 <= code <= 149 or 210 <= code <= 239 or 1010 <= code <= 1059


def _int_code(code: int) -> bool:
    return 60 <= code <= 99 or 170 <= code <= 179 or 270 <= code <= 289 or 370 <= code <= 389 or 1060 <= code <= 1071


@dataclass
class Entity:
    type: str
    codes: list[tuple[int, str]] = field(default_factory=list)

    def get(self, code: int, default=None):
        for c, v in self.codes:
            if c == code:
                return v
        return default

    def all(self, code: int) -> list[str]:
        return [v for c, v in self.codes if c == code]

    def num(self, code: int, default: float | None = None) -> float | None:
        v = self.get(code)
        return default if v is None else float(v)

    @property
    def layer(self) -> str:
        return self.get(8, "0")


@dataclass
class DxfDoc:
    header: dict[str, list[tuple[int, str]]]
    entities: list[Entity]
    entity_count: int
    encoding: str

    def insunits(self) -> int | None:
        vals = self.header.get("$INSUNITS") or []
        for c, v in vals:
            if c == 70:
                try:
                    return int(v)
                except ValueError:
                    return None
        return None


def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise DocumentError("invalid_document", "parse", "텍스트로 읽을 수 없는 DXF 입니다")


def _pairs(text: str):
    lines = text.splitlines()
    if len(lines) % 2 == 1 and lines[-1].strip() == "":
        lines = lines[:-1]
    if len(lines) < 2 or len(lines) % 2 == 1:
        raise DocumentError("invalid_document", "parse", "그룹 코드 · 값 쌍이 맞지 않습니다")
    for i in range(0, len(lines), 2):
        try:
            code = int(lines[i].strip())
        except ValueError:
            raise DocumentError("invalid_document", "parse", "그룹 코드가 정수가 아닙니다") from None
        value = lines[i + 1].strip() if code not in (1, 3) else lines[i + 1].rstrip("\r\n")
        if _float_code(code):
            try:
                x = float(value)
            except ValueError:
                raise DocumentError("invalid_document", "parse", "좌표 · 실수 값이 숫자가 아닙니다") from None
            if not math.isfinite(x):
                raise DocumentError("invalid_document", "parse", "좌표 · 실수 값이 유한하지 않습니다")
        elif _int_code(code):
            try:
                int(value)
            except ValueError:
                raise DocumentError("invalid_document", "parse", "정수 그룹 값이 정수가 아닙니다") from None
        elif code in (1, 3) and len(value) > TEXT_MAX:
            value = value[:TEXT_MAX]
        yield code, value


def _keep(entities: list[Entity], e: Entity) -> int:
    """모델 공간 요소만 남긴다(종이 공간 · 하위 레코드 제외). 남겼으면 1."""
    if e.type.startswith("#PAPER:") or e.type in SUBRECORDS:
        return 0
    entities.append(e)
    return 1


def read(raw: bytes, *, max_entities: int = 20000) -> DxfDoc:
    """→ DxfDoc. 형식 · 파싱 오류는 DocumentError(invalid_document), 엔티티 상한 초과는 DocumentError(document_too_large)."""
    if raw.lstrip()[:len(BINARY_SENTINEL)] == BINARY_SENTINEL or b"\x00" in raw[:4096]:
        raise DocumentError("invalid_document", "binary", "바이너리 DXF 는 받지 않습니다")
    text, enc = _decode(raw)
    header: dict[str, list[tuple[int, str]]] = {}
    entities: list[Entity] = []
    sections: list[str] = []
    section: str | None = None
    expect_name = False
    var: str | None = None
    cur: Entity | None = None
    count = 0
    seen_eof = False
    for code, value in _pairs(text):
        if seen_eof:
            break
        if code == 999:
            continue
        if expect_name:
            if code != 2:
                raise DocumentError("invalid_document", "parse", "SECTION 다음에 이름(2)이 없습니다")
            section = value.upper()
            sections.append(section)
            expect_name = False
            continue
        if code == 0:
            v = value.upper()
            if section == "ENTITIES" and cur is not None:
                count += _keep(entities, cur)
                cur = None
                if count > max_entities:
                    raise DocumentError("document_too_large", "entities", f"모델 공간 요소가 {max_entities:,}개를 넘습니다")
            if v == "SECTION":
                if section is not None:
                    raise DocumentError("invalid_document", "parse", "SECTION 이 닫히지 않았습니다")
                expect_name = True
                continue
            if v == "ENDSEC":
                if section is None:
                    raise DocumentError("invalid_document", "parse", "열리지 않은 ENDSEC 입니다")
                section = None
                var = None
                continue
            if v == "EOF":
                seen_eof = True
                continue
            if section is None:
                raise DocumentError("invalid_document", "parse", "구간 밖 레코드입니다")
            if section == "ENTITIES":
                cur = Entity(v)
            continue
        if section == "HEADER":
            if code == 9:
                var = value.upper()
                header.setdefault(var, [])
            elif var is not None:
                header[var].append((code, value))
        elif section == "ENTITIES" and cur is not None:
            cur.codes.append((code, value))
            if code == 67 and value.strip() == "1":
                cur.type = "#PAPER:" + cur.type
        # 그 밖 구간(TABLES · BLOCKS · OBJECTS …)은 형식만 확인한다
    if cur is not None:
        count += _keep(entities, cur)
    if section is not None or expect_name:
        raise DocumentError("invalid_document", "parse", "닫히지 않은 구간이 있습니다")
    if not sections:
        raise DocumentError("invalid_document", "parse", "DXF 구간(SECTION)이 없습니다")
    if count > max_entities:
        raise DocumentError("document_too_large", "entities", f"모델 공간 요소가 {max_entities:,}개를 넘습니다")
    return DxfDoc(header=header, entities=entities, entity_count=count, encoding=enc)


def resolve_unit(doc: DxfDoc, override: str | None) -> str:
    """원본 단위 — 헤더 $INSUNITS(1 · 4 · 5 · 6) 우선, 아니면 unit_override(mm · inch), 둘 다 없으면 rule unit."""
    u = INSUNITS.get(doc.insunits() or 0)
    if u:
        return u
    if override in OVERRIDES:
        return override
    raise DocumentError("invalid_document", "unit", "도면 단위가 없습니다 — unit_override(mm · inch)를 지정하세요")
