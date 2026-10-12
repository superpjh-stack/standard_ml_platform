#!/bin/bash
# 목적: Claude가 응답을 끝내기 직전(Stop 이벤트)에
#       미등록 이슈가 없는지 한 번 더 점검시킨다.
# 규약: exit 2 + stderr → Claude가 멈추지 않고 stderr를 지시로 받아 계속 작업
#       exit 0          → 정상 종료 허용

INPUT=$(cat)  # Claude Code가 stdin으로 넘기는 이벤트 JSON

# [무한루프 방지] 이미 이 훅 때문에 이어서 작업한 턴이면 종료 허용
if [ "$(jq -r '.stop_hook_active' <<<"$INPUT")" = "true" ]; then
  exit 0
fi

# [비용 절감] Stop은 '작업 완료'가 아니라 '매 응답 종료'마다 발생한다.
# 직전 점검 이후 코드 변경이 없으면(단순 질의응답 등) 건너뛴다.
SESSION_ID=$(jq -r '.session_id' <<<"$INPUT")
STATE_FILE="/tmp/claude-issue-check-${SESSION_ID}"

# 작업 트리 상태를 해시로 요약 (git 내장 명령이라 OS 무관)
CURRENT=$({ git status --porcelain; git diff; } 2>/dev/null | git hash-object --stdin)
# 첫 실행 시 비교 기준은 '변경 없음' 상태의 해시
LAST=$(cat "$STATE_FILE" 2>/dev/null || git hash-object --stdin </dev/null)

[ "$CURRENT" = "$LAST" ] && exit 0   # 변경 없음 → 점검 생략
echo "$CURRENT" > "$STATE_FILE"      # 이번 상태를 점검 완료로 기록

# stderr 내용이 Claude에게 다음 지시로 전달된다
cat >&2 <<'EOF'
종료 전 점검: 이번 작업에서 발견했지만 해결하지 않은 문제(버그, 실패 테스트,
임시 우회, 보류한 TODO)가 있으면 CLAUDE.md의 '이슈 자동 등록 규칙'에 따라
gh로 등록하라. 없으면 추가 작업 없이 '등록할 이슈 없음'이라고만 답하라.
EOF
exit 2
