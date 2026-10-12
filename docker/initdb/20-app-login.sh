#!/bin/sh
# 앱 LOGIN 역할 — mlp_app 의 구성원 (decisions.md D-123 · DEF-QA2-009 · 이슈 #7 · #16 · followups F7-7).
# postgres 공식 이미지의 첫 기동 초기화가 10-schema.sql(테이블 · mlp_app 권한) 다음에 이 파일을 실행한다.
# 앱(MLP_DB_DSN)은 DB 소유자(POSTGRES_USER)가 아니라 이 역할로 붙는다 — 소유자 · 슈퍼유저는 트리거를 DDL 로 끌 수 있으므로
# 추가만 보호의 둘째 겹은 권한이다. 이름 · 비밀번호는 .env.deploy 의 MLP_DB_APP_USER · MLP_DB_APP_PASSWORD(저장소에 값 0).
# 비밀번호는 명령줄에 싣지 않고 psql \getenv 로 읽어 format(%L) 리터럴로만 넣는다. 다시 돌려도 같다(멱등).
if [ -z "${MLP_DB_APP_USER:-}" ] || [ -z "${MLP_DB_APP_PASSWORD:-}" ]; then
    echo "20-app-login: MLP_DB_APP_USER · MLP_DB_APP_PASSWORD 가 필요하다 (.env.deploy — docker/deploy.env.example)" >&2
    exit 1
fi
if [ "${MLP_DB_APP_USER}" = "${POSTGRES_USER:-postgres}" ]; then
    echo "20-app-login: 앱 계정은 DB 소유자(POSTGRES_USER)와 달라야 한다 (D-123)" >&2
    exit 1
fi
psql -v ON_ERROR_STOP=1 -q --username "${POSTGRES_USER:-postgres}" --dbname "${POSTGRES_DB:-postgres}" <<'SQL'
\getenv app_user MLP_DB_APP_USER
\getenv app_pw MLP_DB_APP_PASSWORD
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT IN ROLE mlp_app', :'app_user')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec
SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT PASSWORD %L', :'app_user', :'app_pw') \gexec
SELECT format('GRANT mlp_app TO %I', :'app_user') \gexec
SQL
