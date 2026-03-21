"""Markdown 보고서를 PDF 또는 인터랙티브 HTML로 변환한다."""

import re
import time
from pathlib import Path
from urllib.parse import urlparse

from log import get_logger

logger = get_logger("report")

from markdown_it import MarkdownIt
from weasyprint import HTML as WeasyHTML

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _render_markdown(md_path: str, *, shorten_urls: bool = False) -> str:
    """마크다운 파일을 읽어 HTML body 문자열로 변환한다."""
    md_file = Path(md_path)
    if not md_file.exists():
        raise FileNotFoundError(f"마크다운 파일을 찾을 수 없습니다: {md_path}")

    md_text = md_file.read_text(encoding="utf-8")
    if shorten_urls:
        md_text = _shorten_urls_for_pdf(md_text)
    md = MarkdownIt("commonmark", {"html": True}).enable("table")
    return md.render(md_text)


def _shorten_urls_for_pdf(md_text: str) -> str:
    """PDF용으로 마크다운 링크의 URL을 도메인만 남기고 축약한다.

    [제목](https://www.aitimes.com/news/...) → 제목 (aitimes.com)
    """
    def _replace(match: re.Match) -> str:
        title = match.group(1)
        url = match.group(2)
        domain = urlparse(url).netloc.replace("www.", "")
        return f"{title} ({domain})"

    return re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", _replace, md_text)


def _load_css(css_path: str) -> str:
    """CSS 파일을 읽어 문자열로 반환한다."""
    css_file = Path(css_path)
    if css_file.exists():
        return css_file.read_text(encoding="utf-8")
    return ""


def _load_template(template_path: str) -> str:
    """템플릿 파일을 읽어 문자열로 반환한다.

    _load_css()와 동일한 로직으로, CSS/JS 등 템플릿 파일을 로드한다.
    파일이 존재하지 않으면 빈 문자열을 반환한다.
    """
    tpl_file = Path(template_path)
    if tpl_file.exists():
        return tpl_file.read_text(encoding="utf-8")
    return ""


def _wrap_sections_with_details(html_body: str) -> str:
    """h2 태그를 기준으로 섹션을 <details>/<summary>로 감싼다.

    인터랙티브 HTML에서 각 카테고리 섹션을 접기/펼치기 가능하게 만드는 함수.

    처리 과정:
    1. html_body에서 모든 <h2>...</h2> 태그의 위치를 찾는다.
    2. 첫 번째 h2 이전의 콘텐츠(제목, 하이라이트 등)는 그대로 유지한다.
    3. 각 h2~다음 h2(또는 문서 끝) 사이의 콘텐츠를
       <details class="category-section" open> 태그로 감싸서
       접기/펼치기 가능하게 변환한다.

    Args:
        html_body: 마크다운에서 변환된 HTML 문자열

    Returns:
        <details>/<summary>로 감싸진 HTML 문자열.
        h2 태그가 없으면 원본을 그대로 반환한다.
    """
    # h2 태그 위치를 모두 찾는다
    h2_pattern = re.compile(r"<h2>(.*?)</h2>", re.DOTALL)
    h2_matches = list(h2_pattern.finditer(html_body))

    if not h2_matches:
        return html_body

    # h2 이전의 콘텐츠 (제목, 하이라이트 등)
    result_parts = [html_body[: h2_matches[0].start()]]

    for i, match in enumerate(h2_matches):
        section_title = match.group(1)
        section_start = match.start()

        # 이 섹션의 끝은 다음 h2 시작 또는 문서 끝
        if i + 1 < len(h2_matches):
            section_end = h2_matches[i + 1].start()
        else:
            section_end = len(html_body)

        # h2 태그 자체를 제외한 섹션 본문
        body_start = match.end()
        section_body = html_body[body_start:section_end]

        result_parts.append(
            f'<details class="category-section" open>\n'
            f"<summary><h2>{section_title}</h2></summary>\n"
            f'<div class="section-content">{section_body}</div>\n'
            f"</details>\n"
        )

    return "".join(result_parts)


def _build_html(
    html_body: str,
    css_content: str,
    *,
    interactive: bool = False,
    interactive_css: str = "",
    interactive_js: str = "",
) -> str:
    """HTML body와 CSS/JS를 조합하여 완전한 HTML 문서를 생성한다.

    Args:
        html_body: 마크다운에서 변환된 HTML body 문자열
        css_content: 기본 CSS 내용 (report.css)
        interactive: 인터랙티브 모드 여부 (검색, 접기/펼치기 등 UI 포함)
        interactive_css: 인터랙티브 모드용 CSS 내용
        interactive_js: 인터랙티브 모드용 JS 내용

    Returns:
        완전한 HTML 문서 문자열
    """
    if interactive:
        combined_css = f"{css_content}\n{interactive_css}".strip()
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>주간 뉴스 큐레이션 리포트</title>
<style>
{combined_css}
</style>
</head>
<body>

<div class="search-container">
    <input type="text" id="search-box" class="search-box"
           placeholder="기사 검색 (2글자 이상 입력)..." autocomplete="off">
    <div id="search-count" class="search-count"></div>
</div>

<div class="controls">
    <button id="btn-expand-all">모두 펼치기</button>
    <button id="btn-collapse-all">모두 접기</button>
</div>

<div id="report-content">
{html_body}
</div>

<button id="btn-top" class="back-to-top" aria-label="맨 위로">&#9650;</button>

<script>
{interactive_js}
</script>
</body>
</html>"""
    else:
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>{css_content}</style>
</head>
<body>
{html_body}
</body>
</html>"""


def markdown_to_pdf(
    md_path: str,
    pdf_path: str,
    css_path: str = str(PROJECT_ROOT / "templates" / "report.css"),
) -> None:
    """마크다운 파일을 PDF로 변환한다.

    Args:
        md_path: 입력 마크다운 파일 경로
        pdf_path: 출력 PDF 파일 경로
        css_path: CSS 파일 경로
    """
    html_body = _render_markdown(md_path, shorten_urls=True)
    css_content = _load_css(css_path)

    full_html = _build_html(html_body, css_content)

    Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
    WeasyHTML(string=full_html).write_pdf(pdf_path)
    logger.info("PDF 생성 완료: %s", pdf_path)


def markdown_to_html(
    md_path: str,
    html_path: str,
    css_path: str = str(PROJECT_ROOT / "templates" / "report.css"),
) -> dict:
    """마크다운 파일을 인터랙티브 HTML로 변환한다.

    Returns:
        dict: 변환 결과 메타 정보 (파일 크기, 소요 시간 등)
    """
    t0 = time.perf_counter()

    html_body = _render_markdown(md_path)

    # h2 섹션을 접기/펼치기 가능하게 변환
    html_body = _wrap_sections_with_details(html_body)

    # 인터랙티브용 CSS/JS를 외부 파일에서 로드
    interactive_css = _load_template(str(PROJECT_ROOT / "templates" / "interactive.css"))
    interactive_js = _load_template(str(PROJECT_ROOT / "templates" / "interactive.js"))

    # 기존 CSS를 참고하되, 인터랙티브용 CSS를 사용
    base_css = _load_css(css_path)

    full_html = _build_html(
        html_body,
        base_css,
        interactive=True,
        interactive_css=interactive_css,
        interactive_js=interactive_js,
    )

    out = Path(html_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(full_html, encoding="utf-8")

    elapsed = time.perf_counter() - t0
    file_size = out.stat().st_size

    logger.info("HTML 생성 완료: %s", html_path)
    logger.info("  파일 크기: %s bytes (%.1f KB)", f"{file_size:,}", file_size / 1024)
    logger.info("  소요 시간: %.3f초", elapsed)

    return {
        "html_path": html_path,
        "file_size_bytes": file_size,
        "elapsed_seconds": round(elapsed, 3),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python report_generator.py <input.md> <output.pdf|html>")
        sys.exit(1)

    src, dst = sys.argv[1], sys.argv[2]
    if dst.endswith(".html"):
        markdown_to_html(src, dst)
    else:
        markdown_to_pdf(src, dst)
