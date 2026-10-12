# outputs/qa3 — QA3 재현 스크립트 · 판정 행

- `env.sh` 의 `<scratch>` 는 QA3 가 쓴 임시 폴더 자리표시(실경로 아님, 의도적으로 그대로 둔다) — 다시 돌릴 때 `MLP_ARTIFACT_DIR` · `MLP_SNAPSHOT_DIR` 를 자기 임시 폴더로 바꿔 `source` 한다(DB 는 `ml_qa3_db`).
