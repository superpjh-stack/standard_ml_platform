"""G-S06(비밀) — 키 문자열 · .env 추적 · IP · 호스트명 0, 등록부에는 환경변수 이름만 (goal §2.1 · D-20).

검사 대상은 커밋될 수 있는 파일 전부(git ls-files --cached --others --exclude-standard).
"""
import re

import yaml

from gatelib import ROOT, Line, read, rel, show, tracked_files

KEY_PATTERNS = {
    "openai": r"sk-(proj-)?[A-Za-z0-9_\-]{20,}",
    "anthropic": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "slack": r"xox[abprs]-[A-Za-z0-9\-]{10,}",
    "slack_webhook": r"hooks\.slack\.com/services/[A-Za-z0-9/]+",
    "aws_key": r"(AKIA|ASIA)[0-9A-Z]{16}",
    "aws_secret": r"aws_secret_access_key\s*[=:]\s*\S{20,}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY",
    "dsn_password": r"postgres(ql)?://[^/\s:@]+:[^@\s]+@",
    "github_token": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "jwt": r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
    "mlp_key": r"mlp_[A-Za-z0-9_\-]{40,}",
}
KEY_RE = {k: re.compile(v) for k, v in KEY_PATTERNS.items()}
IPV4 = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")
URL = re.compile(r"[a-z][a-z0-9+.\-]*://([A-Za-z0-9.\-]+)")
HOSTLIKE = re.compile(r"(?<![A-Za-z0-9.\-])(srv\d+\.[a-z.]+|[a-z0-9\-]+\.(?:hstgr\.cloud|amazonaws\.com|azure\.com|cloudapp\.net|ngrok\.io|internal|lan|corp))(?![A-Za-z0-9\-])")
SAFE_IPS = {"127.0.0.1", "0.0.0.0"}
SAFE_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "json-schema.org"}
LOCK_HOSTS = {"pypi.org", "files.pythonhosted.org", "registry.npmjs.org", "github.com", "opencollective.com", "tidelift.com"}  # 잠금 파일의 패키지 출처 · 후원 링크
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".parquet", ".joblib", ".ico", ".woff", ".woff2"}
SECRET_KEYS = re.compile(r"(password|passwd|secret|token|api_key|apikey|dsn|webhook|url|key)$", re.I)


def safe_host(host: str) -> bool:
    """허용 호스트: 루프백 · 스키마 URL · RFC 2606 / RFC 6761 §6.4 예약 최상위 이름 `.invalid`(DNS 에 존재할 수 없다 —
    QA 탐침의 가짜 CORS · 원천 URL). `.invalid` 만 — `.test` · `.example` · 그 밖은 그대로 FAIL (D-125)."""
    host = host.lower().rstrip(".")
    return host in SAFE_HOSTS or host == "invalid" or host.endswith(".invalid")


def _version_like(m: re.Match, txt: str) -> bool:
    """네 마디 버전 문자열은 IP 가 아니다 — 앞 문맥으로 거른다."""
    before = txt[max(0, m.start() - 12): m.start()]
    return bool(re.search(r"(version|v|==|@|\^|~|>=)\s*[\"']?$", before))


def run() -> list[Line]:
    files = tracked_files()
    rels = [rel(f) for f in files]
    problems: list[str] = []
    if any(r == ".env" or (r.startswith(".env.") and r != ".env.example") for r in rels):
        problems.append(".env 가 추적됨")
    if ".env" not in read(ROOT / ".gitignore").split():
        problems.append(".gitignore 에 .env 없음")
    for f, r in zip(files, rels):
        if f.suffix in SKIP_SUFFIX or "node_modules" in r:
            continue
        txt = read(f)
        for name, pat in KEY_RE.items():
            if pat.search(txt):
                problems.append(f"키처럼 보이는 값({name}): {r}")
        for m in IPV4.finditer(txt):
            ip = m.group(0)
            if ip not in SAFE_IPS and all(int(g) <= 255 for g in m.groups()) and not _version_like(m, txt):
                problems.append(f"IP 주소: {r}")
                break
        is_lock = r.endswith(("uv.lock", "package-lock.json"))
        for m in URL.finditer(txt):
            host = m.group(1).lower()
            if safe_host(host) or (is_lock and host in LOCK_HOSTS):
                continue
            problems.append(f"호스트 {host!r}: {r}")
            break
        if HOSTLIKE.search(txt):
            problems.append(f"호스트명: {r}")
    # 등록부 — *_env 는 MLP_ 이름, 비밀처럼 보이는 키에 값 0
    env_names = 0
    for f in sorted((ROOT / "tenants").rglob("*.yaml")):
        cfg = yaml.safe_load(read(f).replace("__code__", "tpl").replace("__name__", "t")) or {}

        def walk(o, path=""):
            nonlocal env_names
            if isinstance(o, dict):
                for k, v in o.items():
                    kp = f"{path}.{k}"
                    if isinstance(k, str) and k.endswith("_env"):
                        if v is not None and not re.fullmatch(r"MLP_[A-Z0-9_]+", str(v)):
                            problems.append(f"{rel(f)}{kp}: 환경변수 이름이 아니다")
                        elif v:
                            env_names += 1
                    elif isinstance(k, str) and SECRET_KEYS.search(k) and isinstance(v, str) and v:
                        problems.append(f"{rel(f)}{kp}: 비밀처럼 보이는 키에 값")
                    walk(v, kp)
            elif isinstance(o, list):
                for v in o:
                    walk(v, path)
        walk(cfg)
    ex = read(ROOT / ".env.example") if (ROOT / ".env.example").is_file() else ""
    bad_ex = [ln for ln in ex.splitlines() if ln and not ln.startswith("#") and not re.fullmatch(r"MLP_[A-Z0-9_]+=", ln)]
    if not ex:
        problems.append(".env.example 없음")
    if bad_ex:
        problems.append(f".env.example 에 값 또는 MLP_ 아닌 이름 {len(bad_ex)}줄")
    if problems:
        return [Line("G-S06", "비밀값", "FAIL", f"{len(problems)}건: " + "; ".join(problems[:6]) + (" …" if len(problems) > 6 else ""))]
    return [Line("G-S06", "비밀값", "PASS", f"추적 파일 {len(files)} · 키 0 · IP 0 · 호스트 0 · .env 비추적 · 등록부 환경변수 이름 {env_names}개(값 0)")]


if __name__ == "__main__":
    raise SystemExit(show(run()))
