# QA 재검증(R2) 전용 환경 — ml_qar2_db 만. ml_db · ml_test_db 쓰기 금지
# QAR2_SCRATCH 는 실행자 임시 폴더(저장소 밖)로 지정한다
: "${QAR2_SCRATCH:?QAR2_SCRATCH 를 임시 폴더로 지정}"
export MLP_DB_DSN="dbname=ml_qar2_db host=/tmp"
export MLP_TEST_DB_DSN="dbname=ml_qar2_db host=/tmp"
export MLP_ARTIFACT_DIR="$QAR2_SCRATCH/art"
export MLP_SNAPSHOT_DIR="$QAR2_SCRATCH/snap"
export OMP_NUM_THREADS=1
export QAR2_PORT=8204
