"""LLM 기반 보고서 생성."""

import re
import shutil
import subprocess
from pathlib import Path

from log import get_logger

logger = get_logger("reporter")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def find_previous_report(output_dir: str, current_date: str) -> str | None:
    """현재 날짜 이전의 가장 최근 보고서 경로를 반환한다."""
    out_path = Path(output_dir)
    if not out_path.exists():
        return None
    md_files = sorted(out_path.glob("*.md"), reverse=True)
    for f in md_files:
        # 날짜 형식 파일만 (YYYY-MM-DD.md), regen 등 제외
        if re.match(r"^\d{4}-\d{2}-\d{2}\.md$", f.name) and f.stem < current_date:
            return str(f)
    return None


def extract_watchpoints(md_path: str) -> str:
    """보고서에서 '다음 주 관전 포인트' 섹션을 추출한다."""
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return ""

    # "## 다음 주 관전 포인트" ~ 다음 "##" 또는 "---" 까지
    match = re.search(
        r"##\s*다음 주 관전 포인트\s*\n(.*?)(?=\n##|\n---|\Z)",
        text,
        re.DOTALL,
    )
    if match:
        content = match.group(1).strip()
        if content:
            return content
    return ""


def _resolve_path(path_str: str) -> Path:
    """프로젝트 루트 기준으로 경로를 정규화한다."""
    path = Path(path_str)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def generate_report(
    slim_file: str,
    md_file: str,
    feedback_file: str | None = None,
    template: str = "templates/curate_prompt.txt",
    prev_watchpoints: str = "",
) -> bool:
    """slim JSON을 읽어 Claude CLI로 마크다운 보고서를 생성한다.

    Args:
        slim_file: 전처리된 경량 JSON 파일 경로
        md_file: 출력 마크다운 파일 경로
        feedback_file: 피드백 파일 경로 (선택)
        template: 프롬프트 템플릿 경로 (프로젝트 루트 기준)
        prev_watchpoints: 이전 보고서의 '다음 주 관전 포인트' 텍스트

    Returns:
        성공 시 True, 실패 시 False
    """
    claude_path = shutil.which("claude")
    if not claude_path:
        logger.error("Claude CLI를 찾을 수 없습니다. `claude` 명령이 PATH에 있어야 합니다.")
        return False

    slim_path = _resolve_path(slim_file)
    output_path = _resolve_path(md_file)
    feedback_path = _resolve_path(feedback_file) if feedback_file else None

    # 프롬프트 조립
    prompt_template_path = PROJECT_ROOT / template
    if not prompt_template_path.exists():
        logger.error("프롬프트 템플릿 없음: %s", prompt_template_path)
        return False

    prompt_template = prompt_template_path.read_text(encoding="utf-8")

    feedback_prompt = ""
    if feedback_path and feedback_path.exists():
        feedback_content = feedback_path.read_text(encoding="utf-8")
        feedback_prompt = (
            f"\n\n또한 아래 피드백을 반영하여 보고서 품질을 개선하세요:\n"
            f"{feedback_content}\n"
        )
        logger.info("피드백 반영: %s", feedback_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    watchpoints_prompt = ""
    if prev_watchpoints:
        watchpoints_prompt = (
            f"\n\n## 지난주 관전 포인트 (팔로업 필요)\n"
            f"아래는 지난주 보고서에서 작성한 '다음 주 관전 포인트'입니다. "
            f"이번 주 기사와 대조하여 팔로업 섹션을 작성하세요:\n"
            f"{prev_watchpoints}\n"
        )
        logger.info("지난주 관전 포인트 반영")

    prompt = prompt_template.format(
        slim_file=str(slim_path),
        md_file=str(output_path),
        feedback_prompt=feedback_prompt,
        watchpoints_prompt=watchpoints_prompt,
    )

    # Claude CLI 호출
    logger.info("Claude 보고서 생성 시작...")
    try:
        result = subprocess.run(
            [claude_path, "-p", prompt, "--allowedTools", "Read,Write,Glob"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
    except OSError as exc:
        logger.error("Claude CLI 실행 실패: %s", exc)
        return False

    if result.returncode != 0:
        error_snippet = (result.stderr or result.stdout or "").strip()[:400]
        logger.error("보고서 생성 실패: %s", error_snippet)
        return False

    if not output_path.exists():
        logger.error("보고서 미생성: %s", output_path)
        return False

    logger.info("보고서 생성 완료: %s", output_path)
    return True
