# 표준 ML 플랫폼 — 회사당 한 벌(D-01) 앱 이미지. 다단계: (1) 콘솔 빌드(web/dist) → (2) Python 런타임.
# 베이스 이미지는 정확한 태그로 고정한다(G-S07 정신 · spec §17 배포). 이미지 태그는 커밋 SHA(docker-compose.yml MLP_GIT_SHA).
# 이미지 안에서 학습하지 않는다 — 기동은 등록부 로드만(G-M06). 모델 산출물은 볼륨 var/ 의 등록부 경로에서만 읽는다.
# 비밀값은 이미지에 넣지 않는다 — 실행 시 env 파일(.env.deploy)로만 들어온다(D-20). .dockerignore 가 .env* 를 뺀다.

# ── 1단계: 콘솔(Vite + React) 빌드 ─────────────────────────────────────────
FROM node:24.18.1-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund --loglevel=error
COPY web/ ./
RUN npm run build

# ── 2단계: uv (정확한 버전) ────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:0.12.1 AS uv

# ── 3단계: Python 런타임 ──────────────────────────────────────────────────
FROM python:3.12.13-slim-bookworm AS runtime
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1
WORKDIR /app
# 의존성 층(잠금 파일 그대로 — --frozen: uv.lock 과 다르면 실패)
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project
# 코드 · 표준 · 팩 · 등록부(회사 차이는 tenants/ 에만)
COPY src ./src
COPY std ./std
COPY packs ./packs
COPY tenants ./tenants
COPY contracts ./contracts
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist ./web/dist
RUN useradd --system --uid 10001 --home /app mlp && mkdir -p /app/var && chown -R mlp /app/var
USER mlp
EXPOSE 8200
# 헬스체크는 compose 에도 있다(G-M11 은 compose 기준으로 판정)
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8200/api/v1/health', timeout=2).status == 200 else 1)"]
CMD ["/app/.venv/bin/uvicorn", "mlcore.api.main:app", "--host", "0.0.0.0", "--port", "8200", "--workers", "1"]
