# QA2 재검증(r2) 전용 — ml_qa2r2_db · 포트 8214. ml_db · ml_test_db 쓰기 금지. QA_SP = 임시 폴더(저장소 밖)
export MLP_DB_DSN="dbname=ml_qa2r2_db host=/tmp"
export MLP_TEST_DB_DSN="dbname=ml_qa2r2_db host=/tmp"
export MLP_ARTIFACT_DIR="${QA_SP}/art"
export MLP_SNAPSHOT_DIR="${QA_SP}/snap"
export MLP_DOCUMENT_DIR="${QA_SP}/docs"
export OMP_NUM_THREADS=1
