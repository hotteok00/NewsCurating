#!/bin/bash
# check_status.sh - 마지막 실행 상태 확인 + 다음 실행 예정 시간 표시

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATUS_FILE="${PROJECT_DIR}/logs/last_run_status.json"
LOGS_DIR="${PROJECT_DIR}/logs"

echo "========================================"
echo " NewsCurating - 실행 상태 확인"
echo "========================================"
echo ""

# 마지막 실행 상태
if [ -f "${STATUS_FILE}" ]; then
    echo "[마지막 실행 정보]"

    DATE=$(python3 -c "import json; d=json.load(open('${STATUS_FILE}')); print(d['date'])" 2>/dev/null)
    STATUS=$(python3 -c "import json; d=json.load(open('${STATUS_FILE}')); print(d['status'])" 2>/dev/null)
    ELAPSED=$(python3 -c "import json; d=json.load(open('${STATUS_FILE}')); print(d['elapsed_seconds'])" 2>/dev/null)
    ARTICLES=$(python3 -c "import json; d=json.load(open('${STATUS_FILE}')); print(d['article_count'])" 2>/dev/null)
    START=$(python3 -c "import json; d=json.load(open('${STATUS_FILE}')); print(d['start_time'])" 2>/dev/null)
    EXIT_CODE=$(python3 -c "import json; d=json.load(open('${STATUS_FILE}')); print(d['exit_code'])" 2>/dev/null)

    if [ "${STATUS}" = "success" ]; then
        STATUS_DISPLAY="SUCCESS"
    else
        STATUS_DISPLAY="FAILURE (exit code: ${EXIT_CODE})"
    fi

    echo "  날짜:       ${DATE}"
    echo "  상태:       ${STATUS_DISPLAY}"
    echo "  시작 시간:  ${START}"
    echo "  소요 시간:  ${ELAPSED}초"
    echo "  기사 수:    ${ARTICLES}개"
    echo "  로그 파일:  ${LOGS_DIR}/${DATE}.log"
else
    echo "[마지막 실행 정보]"
    echo "  아직 실행 기록이 없습니다."
fi

echo ""

# 다음 예정 실행 시간 계산
echo "[다음 예정 실행]"

# 현재 cron에 등록되어 있는지 확인
CRON_REGISTERED=$(crontab -l 2>/dev/null | grep -c "NewsCurating weekly run" || true)

if [ "${CRON_REGISTERED}" -gt 0 ]; then
    # 다음 월요일 09:00 계산
    DOW=$(date +%u)  # 1=월요일, 7=일요일
    if [ "${DOW}" -eq 1 ]; then
        CURRENT_HOUR=$(date +%H)
        if [ "${CURRENT_HOUR}" -lt 9 ]; then
            DAYS_UNTIL=0
        else
            DAYS_UNTIL=7
        fi
    else
        DAYS_UNTIL=$(( (8 - DOW) % 7 ))
        if [ "${DAYS_UNTIL}" -eq 0 ]; then
            DAYS_UNTIL=7
        fi
    fi

    NEXT_DATE=$(date -d "+${DAYS_UNTIL} days" +%Y-%m-%d 2>/dev/null || date -v+${DAYS_UNTIL}d +%Y-%m-%d 2>/dev/null)
    echo "  스케줄:     매주 월요일 09:00"
    echo "  다음 실행:  ${NEXT_DATE} 09:00"
    echo "  cron 상태:  등록됨"
else
    echo "  cron 상태:  미등록"
    echo "  등록하려면: ./scripts/setup_cron.sh"
fi

echo ""

# 최근 로그 파일 목록
echo "[최근 로그 파일]"
LOG_FILES=$(ls -t "${LOGS_DIR}"/*.log 2>/dev/null | head -5)
if [ -n "${LOG_FILES}" ]; then
    for f in ${LOG_FILES}; do
        SIZE=$(du -h "$f" | cut -f1)
        echo "  $(basename "$f")  (${SIZE})"
    done
else
    echo "  로그 파일 없음"
fi
