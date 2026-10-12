# QA2-1 전용 환경 — ml_db · ml_test_db 를 건드리지 않는다
export MLP_DB_DSN="dbname=ml_qa21_db host=/tmp"
export MLP_TEST_DB_DSN="dbname=ml_qa21_db host=/tmp"
export MLP_ARTIFACT_DIR="$PWD/outputs/qa2-1/var/artifacts"
export MLP_SNAPSHOT_DIR="$PWD/outputs/qa2-1/var/snapshots"
export MLP_DOCUMENT_DIR="$PWD/outputs/qa2-1/var/documents"
export OMP_NUM_THREADS=1
