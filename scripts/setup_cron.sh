#!/bin/bash
# setup_cron.sh - cron 등록 스크립트
# 매주 월요일 오전 9시에 run_with_logging.sh 실행
#
# 사용법:
#   ./scripts/setup_cron.sh          # 실제 cron 등록
#   ./scripts/setup_cron.sh --dry-run # 등록할 내용만 출력 (실제 등록 안 함)

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WRAPPER="${PROJECT_DIR}/scripts/run_with_logging.sh"
CRON_SCHEDULE="0 9 * * 1"
CRON_ENTRY="${CRON_SCHEDULE} ${WRAPPER}"
CRON_MARKER="# NewsCurating weekly run"

DRY_RUN=false
if [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
fi

echo "========================================"
echo " NewsCurating - Cron 설정"
echo "========================================"
echo ""
echo "스케줄:  매주 월요일 09:00"
echo "명령:    ${WRAPPER}"
echo "cron 항목:"
echo "  ${CRON_ENTRY} ${CRON_MARKER}"
echo ""

if [ "${DRY_RUN}" = true ]; then
    echo "[dry-run] 실제 cron 등록을 수행하지 않습니다."
    echo "[dry-run] 등록하려면 --dry-run 플래그 없이 실행하세요."
    exit 0
fi

# 기존 NewsCurating 항목이 있으면 제거 후 재등록
EXISTING_CRON=$(crontab -l 2>/dev/null || true)

if echo "${EXISTING_CRON}" | grep -qF "NewsCurating weekly run"; then
    echo "기존 NewsCurating cron 항목을 제거합니다..."
    EXISTING_CRON=$(echo "${EXISTING_CRON}" | grep -vF "NewsCurating weekly run")
fi

# 새 항목 추가
NEW_CRON="${EXISTING_CRON}
${CRON_ENTRY} ${CRON_MARKER}"

# 빈 줄 정리
NEW_CRON=$(echo "${NEW_CRON}" | sed '/^$/d')

echo "${NEW_CRON}" | crontab -

echo "cron 등록 완료!"
echo ""
echo "확인:"
crontab -l | grep "NewsCurating"
