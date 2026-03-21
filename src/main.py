"""NewsCurating 메인 오케스트레이터."""

import argparse
from datetime import date
from pathlib import Path

from config import load_config
from crawler import crawl_sources, save_crawled_data, load_prev_urls, find_latest_crawled_json, PipelineMetrics
from llm_reporter import extract_watchpoints, find_previous_report, generate_report
from log import get_logger
from preprocessor import preprocess
from report_generator import markdown_to_pdf, markdown_to_html
from sources import load_sources

logger = get_logger("main")

# 프로젝트 루트 디렉토리 (src/ 의 부모)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def cmd_crawl(config: dict, incremental: bool = False, prev_file: str | None = None) -> str | None:
    """소스에서 URL을 파싱하고 크롤링한다."""
    bookmarks = load_sources(config)
    logger.info("%d개 URL 발견", len(bookmarks))

    if not bookmarks:
        logger.info("크롤링할 북마크가 없습니다.")
        return None

    # 증분 크롤링: 이전 데이터에서 URL 로드
    prev_urls = None
    if incremental:
        if prev_file:
            prev_urls = load_prev_urls(prev_file)
        else:
            latest = find_latest_crawled_json(config["crawled_dir"])
            if latest:
                prev_urls = load_prev_urls(latest)
            else:
                logger.info("이전 크롤링 데이터가 없습니다. 전체 크롤링을 진행합니다.")

    articles = crawl_sources(bookmarks, config.get("crawl", {}), prev_urls=prev_urls)
    return save_crawled_data(articles, config["crawled_dir"])


def cmd_pdf(config: dict, md_path: str | None = None) -> None:
    """마크다운을 PDF로 변환한다."""
    if not md_path:
        md_path = f"{config['output_dir']}/{date.today().isoformat()}.md"

    pdf_path = md_path.replace(".md", ".pdf")
    css_path = config.get("report", {}).get("css_template", "templates/report.css")
    markdown_to_pdf(md_path, pdf_path, css_path)


def cmd_html(config: dict, md_path: str | None = None) -> None:
    """마크다운을 인터랙티브 HTML로 변환한다."""
    if not md_path:
        md_path = f"{config['output_dir']}/{date.today().isoformat()}.md"

    html_path = md_path.replace(".md", ".html")
    css_path = config.get("report", {}).get("css_template", "templates/report.css")
    markdown_to_html(md_path, html_path, css_path)


def cmd_pipeline(config: dict, incremental: bool = False, prev_file: str | None = None) -> None:
    """전체 파이프라인을 실행하며 각 단계별 시간을 측정한다."""
    import os
    os.chdir(PROJECT_ROOT)  # 프로젝트 루트에서 실행
    # config에서 증분 크롤링 설정 확인
    incremental = incremental or config.get("crawl", {}).get("incremental", False)
    metrics = PipelineMetrics()
    today = date.today().isoformat()
    json_file = f"{config['crawled_dir']}/{today}.json"
    slim_file = f"{config['crawled_dir']}/{today}_slim.json"
    md_file = f"{config['output_dir']}/{today}.md"
    feedback_file = config.get("feedback", {}).get("file", "feedback/weekly_feedback.md")

    # [1/5] 크롤링
    logger.info("[1/5] 크롤링")
    with metrics.measure("크롤링"):
        cmd_crawl(config, incremental=incremental, prev_file=prev_file)

    if not Path(json_file).exists():
        logger.error("크롤링 결과 없음: %s", json_file)
        return

    # [2/5] 전처리 (중복 제거 + 마스터 요약 구조 변환)
    logger.info("[2/5] 전처리 + 구조화")
    with metrics.measure("전처리"):
        preprocess(json_file, slim_file, config=config.get("preprocessor"))

    # [3/5] 보고서 생성 (Claude)
    logger.info("[3/5] 보고서 생성")
    # 이전 보고서에서 관전 포인트 추출
    prev_report = find_previous_report(config["output_dir"], today)
    prev_watchpoints = ""
    if prev_report:
        prev_watchpoints = extract_watchpoints(prev_report)
        if prev_watchpoints:
            logger.info("지난주 관전 포인트 로드: %s", prev_report)
    with metrics.measure("보고서 생성"):
        if not generate_report(slim_file, md_file, feedback_file, prev_watchpoints=prev_watchpoints):
            return

    # [4/5] PDF 변환
    logger.info("[4/5] PDF 변환")
    with metrics.measure("PDF 변환"):
        cmd_pdf(config, md_file)

    # [5/5] HTML 변환
    logger.info("[5/5] HTML 변환")
    with metrics.measure("HTML 변환"):
        cmd_html(config, md_file)

    # 결과 출력 및 저장
    logger.info(metrics.report())
    metrics.save()


def main() -> None:
    parser = argparse.ArgumentParser(description="NewsCurating - 주간 뉴스 큐레이션")
    parser.add_argument("command", choices=["crawl", "pdf", "html", "pipeline"],
                        help="crawl: 크롤링만, pdf: MD→PDF, html: MD→HTML, pipeline: 전체 (시간 측정)")
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    parser.add_argument("--md-path", help="PDF/HTML 변환 시 마크다운 파일 경로")
    parser.add_argument("--incremental", action="store_true",
                        help="증분 크롤링: 이전 데이터와 비교하여 새 기사만 수집")
    parser.add_argument("--prev-file", help="증분 크롤링 시 비교할 이전 JSON 파일 경로")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "crawl":
        cmd_crawl(config, incremental=args.incremental, prev_file=args.prev_file)
    elif args.command == "pdf":
        cmd_pdf(config, args.md_path)
    elif args.command == "html":
        cmd_html(config, args.md_path)
    elif args.command == "pipeline":
        cmd_pipeline(config, incremental=args.incremental, prev_file=args.prev_file)


if __name__ == "__main__":
    main()
