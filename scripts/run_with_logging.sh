#!/bin/bash
# run_with_logging.sh - run_curate.sh 실행 래퍼 (로깅 + 상태 기록)
# 용도: cron에서 직접 호출하거나, 수동 실행 시에도 사용 가능

set -o pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOGS_DIR="${PROJECT_DIR}/logs"
DATE=$(date +%Y-%m-%d)
LOG_FILE="${LOGS_DIR}/${DATE}.log"
STATUS_FILE="${LOGS_DIR}/last_run_status.json"

# 실행할 명령 (인자가 없으면 기본값 사용)
COMMAND="${1:-${PROJECT_DIR}/run_curate.sh}"

mkdir -p "${LOGS_DIR}"

# 시작 시간 기록
START_TIME=$(date +%s)
START_ISO=$(date -Iseconds)

echo "============================================" >> "${LOG_FILE}"
echo "실행 시작: ${START_ISO}" >> "${LOG_FILE}"
echo "명령: ${COMMAND}" >> "${LOG_FILE}"
echo "============================================" >> "${LOG_FILE}"

# 명령 실행, stdout + stderr 를 로그에 기록하면서 동시에 터미널에도 출력
bash "${COMMAND}" 2>&1 | tee -a "${LOG_FILE}"
EXIT_CODE=${PIPESTATUS[0]}

# 종료 시간 기록
END_TIME=$(date +%s)
END_ISO=$(date -Iseconds)
ELAPSED=$((END_TIME - START_TIME))

# 기사 수 추출 시도 (로그에서 크롤링 결과 파싱)
ARTICLE_COUNT=$(grep -oP '성공적으로 크롤링된 기사: \K[0-9]+' "${LOG_FILE}" 2>/dev/null | tail -1)
ARTICLE_COUNT=${ARTICLE_COUNT:-0}

# 상태 결정
if [ "${EXIT_CODE}" -eq 0 ]; then
    STATUS="success"
else
    STATUS="failure"
fi

echo "" >> "${LOG_FILE}"
echo "============================================" >> "${LOG_FILE}"
echo "실행 종료: ${END_ISO}" >> "${LOG_FILE}"
echo "소요 시간: ${ELAPSED}초" >> "${LOG_FILE}"
echo "종료 코드: ${EXIT_CODE} (${STATUS})" >> "${LOG_FILE}"
echo "============================================" >> "${LOG_FILE}"

# 상태 JSON 생성
cat > "${STATUS_FILE}" <<ENDJSON
{
  "date": "${DATE}",
  "status": "${STATUS}",
  "exit_code": ${EXIT_CODE},
  "start_time": "${START_ISO}",
  "end_time": "${END_ISO}",
  "elapsed_seconds": ${ELAPSED},
  "article_count": ${ARTICLE_COUNT},
  "log_file": "${LOG_FILE}",
  "command": "${COMMAND}"
}
ENDJSON

echo ""
echo "[run_with_logging] 완료 - 상태: ${STATUS}, 소요시간: ${ELAPSED}초"
echo "[run_with_logging] 로그: ${LOG_FILE}"
echo "[run_with_logging] 상태파일: ${STATUS_FILE}"

exit ${EXIT_CODE}
