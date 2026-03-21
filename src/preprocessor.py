"""크롤링 데이터를 Claude 분석 전에 압축/필터링한다.

목적: Claude 입력 토큰을 줄여 분석 시간을 단축.
  - 중복 기사 제거 (제목 유사도)
  - 본문 → 요약 압축 (title + summary 300자로 충분)
  - 빈 콘텐츠 / 실패 항목 제거
  - 관련 기사 그룹핑
  - LLM 기반 토픽 클러스터링
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from log import get_logger

logger = get_logger("preprocessor")

# 기본값 상수
_DEFAULT_DEDUP_THRESHOLD = 0.5
_DEFAULT_GROUPING_THRESHOLD = 0.3
_DEFAULT_MIN_TITLE_LENGTH = 5
_DEFAULT_MAX_SUMMARY_LENGTH = 300


def preprocess(input_path: str, output_path: str, config: dict | None = None) -> dict:
    """크롤링 JSON을 압축하여 Claude용 경량 JSON을 생성한다.

    Args:
        input_path: 크롤링 결과 JSON 파일 경로
        output_path: 경량 JSON 출력 경로
        config: preprocessor 설정 dict (없으면 기본값 사용)

    Returns: 통계 dict
    """
    if config is None:
        config = {}

    dedup_threshold = config.get("dedup_threshold", _DEFAULT_DEDUP_THRESHOLD)
    grouping_threshold = config.get("grouping_threshold", _DEFAULT_GROUPING_THRESHOLD)
    min_title_length = config.get("min_title_length", _DEFAULT_MIN_TITLE_LENGTH)
    max_summary_length = config.get("max_summary_length", _DEFAULT_MAX_SUMMARY_LENGTH)

    with open(input_path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    original_count = len(articles)

    # 1) fetch_status != "ok" 제거
    articles = [a for a in articles if a.get("fetch_status") == "ok"]
    after_status = len(articles)

    # 2) 제목이 너무 짧거나 없는 것 제거
    articles = [a for a in articles if len(a.get("title", "").strip()) >= min_title_length]
    after_title = len(articles)

    # 3) 중복 제거 (Jaccard 키워드 유사도)
    articles = _deduplicate(articles, threshold=dedup_threshold)
    after_dedup = len(articles)

    # 4) 관련 기사 그룹핑
    groups = _group_related(articles, threshold=grouping_threshold)

    # 5) 경량 포맷으로 변환
    slim_articles = []
    for group in groups:
        if len(group) == 1:
            slim_articles.append(_to_slim(group[0], max_summary_length))
        else:
            slim_articles.append(_merge_group(group, max_summary_length))

    # 6) content_quality가 "low"이고 본문이 없는 기사 제거
    if config.get("filter_low_quality", True):
        before_quality = len(slim_articles)
        slim_articles = [a for a in slim_articles if not (
            a.get("content_quality") == "low" and len(a.get("content", "")) < 50
        )]
        quality_filtered = before_quality - len(slim_articles)
    else:
        quality_filtered = 0

    # 7) ref_id 부여 (인용 번호)
    for i, article in enumerate(slim_articles, 1):
        article["ref_id"] = i

    # 7) LLM 토픽 클러스터링
    topic_clustering = config.get("topic_clustering", True)
    topics = []
    if topic_clustering:
        topics = _cluster_topics(slim_articles)
        if topics:
            logger.info("  토픽 클러스터링: %d개 토픽 발견", len(topics))

    # 최종 출력 구조: topics + articles
    output_data = {
        "topics": topics,
        "articles": slim_articles,
    }

    # 저장
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    original_size = Path(input_path).stat().st_size
    slim_size = Path(output_path).stat().st_size

    stats = {
        "original_count": original_count,
        "after_status_filter": after_status,
        "after_title_filter": after_title,
        "after_dedup": after_dedup,
        "groups": len(groups),
        "final_count": len(slim_articles),
        "topic_count": len(topics),
        "original_size_kb": original_size / 1024,
        "slim_size_kb": slim_size / 1024,
        "reduction_pct": (1 - slim_size / original_size) * 100,
    }

    logger.info("전처리 완료:")
    logger.info("  기사: %d → %d개 (%d개 제거)", original_count, len(slim_articles), original_count - len(slim_articles))
    logger.info("    상태 필터: -%d", original_count - after_status)
    logger.info("    제목 필터: -%d", after_status - after_title)
    logger.info("    중복 제거: -%d", after_title - after_dedup)
    logger.info("    그룹 병합: -%d", after_dedup - (len(slim_articles) + quality_filtered))
    if quality_filtered:
        logger.info("    품질 필터: -%d", quality_filtered)
    if topics:
        logger.info("    토픽: %d개", len(topics))
    logger.info("  크기: %.0fKB → %.0fKB (%.0f%% 감소)", stats['original_size_kb'], stats['slim_size_kb'], stats['reduction_pct'])

    return stats


def _merge_group(group: list[dict], max_summary_length: int) -> dict:
    """관련 기사 그룹을 대표 1개 + 관련 URL 목록으로 병합한다."""
    main = max(group, key=lambda a: len(a.get("summary", "") + a.get("content", "")))
    related_urls = [a["url"] for a in group if a["url"] != main["url"]]
    slim = _to_slim(main, max_summary_length)
    slim["related"] = related_urls
    slim["related_titles"] = [a["title"] for a in group if a["url"] != main["url"]]
    return slim


def _to_slim(article: dict, max_summary_length: int = _DEFAULT_MAX_SUMMARY_LENGTH) -> dict:
    """기사를 마스터 요약 구조로 변환한다."""
    url = article.get("url", "")
    summary_text = article.get("summary", "").strip()
    content_text = article.get("content", "").strip()

    # source_type 판별
    source_type = _detect_source_type(url)

    # key_facts 추출 (정규식 기반) — content 전체에서 추출
    combined_text = f"{article.get('title', '')} {summary_text} {content_text}"
    key_facts = _extract_key_facts(combined_text)

    # content_quality 판단
    content_quality = _assess_quality(summary_text, content_text)

    result = {
        "url": url,
        "title": article.get("title", ""),
        "date": article.get("date", ""),
        "source_type": source_type,
        "content": _compress_content(summary_text, content_text, max_summary_length),
        "key_facts": key_facts,
        "content_quality": content_quality,
        "source_group": article.get("source_group", ""),
    }
    return result


def _compress_content(summary: str, content: str, max_length: int) -> str:
    """LLM 입력용 본문을 요약/절단하여 토큰 사용량을 줄인다."""
    text = summary.strip() or content.strip()
    if not text:
        return ""

    if len(text) <= max_length:
        return text

    if max_length <= 3:
        return text[:max_length]

    return text[: max_length - 3].rstrip() + "..."


# ─── 팩트 추출 패턴 ─────────────────────────────────────────────────────

# 금액 패턴: $110, 4.5억, 30조원, 200억달러, 6,600억원 등
_MONEY_PATTERN = re.compile(
    r"(?:\$[\d,.]+(?:\s*[조억만])?|"
    r"[\d,.]+\s*(?:조|억|만)\s*(?:원|달러|유로|엔)|"
    r"[\d,.]+\s*(?:달러|원|유로|엔))",
)

# 비율/수치 패턴: 90%, 96% 요격률, 20배, 36% 향상 등
_PERCENT_PATTERN = re.compile(r"[\d,.]+\s*%\s*[가-힣]*")
_MULTIPLIER_PATTERN = re.compile(r"[\d,.]+\s*배\s*[가-힣]*")

# 인원/수량 패턴: 5000명, 16000명, 15개 등
_COUNT_PATTERN = re.compile(r"[\d,.]+\s*(?:명|개|건|곳|대|척)")

# 기간/날짜 패턴: 10년, 5개월, 7일 등
_DURATION_PATTERN = re.compile(r"[\d]+\s*(?:년|개월|일|시간|분)\s*[가-힣]*")


def _extract_key_facts(text: str) -> list[str]:
    """텍스트에서 핵심 수치/팩트를 추출한다."""
    facts = set()

    for pattern in [_MONEY_PATTERN, _PERCENT_PATTERN, _MULTIPLIER_PATTERN, _COUNT_PATTERN]:
        for match in pattern.finditer(text):
            fact = match.group().strip()
            if len(fact) >= 3:  # 너무 짧은 것 제외
                facts.add(fact)

    # 중복 제거 후 최대 8개
    return sorted(facts, key=lambda x: text.index(x))[:8]


def _detect_source_type(url: str) -> str:
    """URL에서 소스 유형을 판별한다."""
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "arxiv.org" in url_lower:
        return "paper"
    if "huggingface.co/papers" in url_lower:
        return "paper"
    if "alphaxiv.org" in url_lower:
        return "paper"
    if "discuss." in url_lower or "forum." in url_lower:
        return "forum"
    return "news"


def _assess_quality(summary: str, content: str) -> str:
    """콘텐츠 품질을 평가한다."""
    summary_len = len(summary.strip())
    content_len = len(content.strip())

    if content_len >= 500 and summary_len >= 100:
        return "high"
    if content_len >= 200 or summary_len >= 100:
        return "high"
    if content_len >= 50 or summary_len >= 30:
        return "medium"
    return "low"


def _deduplicate(articles: list[dict], threshold: float = 0.7) -> list[dict]:
    """제목 유사도로 중복 기사를 제거한다."""
    keep = []
    seen_titles = []

    for article in articles:
        title = _normalize_title(article.get("title", ""))
        is_dup = False
        for seen in seen_titles:
            if _title_similarity(title, seen) >= threshold:
                is_dup = True
                break
        if not is_dup:
            keep.append(article)
            seen_titles.append(title)

    return keep


def _group_related(articles: list[dict], threshold: float = 0.5) -> list[list[dict]]:
    """관련 기사를 그룹으로 묶는다."""
    groups = []
    used = set()

    for i, article in enumerate(articles):
        if i in used:
            continue
        group = [article]
        used.add(i)
        title_i = _normalize_title(article.get("title", ""))

        for j in range(i + 1, len(articles)):
            if j in used:
                continue
            title_j = _normalize_title(articles[j].get("title", ""))
            if _title_similarity(title_i, title_j) >= threshold:
                group.append(articles[j])
                used.add(j)

        groups.append(group)

    return groups


def _normalize_title(title: str) -> str:
    """제목을 정규화한다."""
    title = re.sub(r"[\[\(].*?[\]\)]", "", title)  # 대괄호/소괄호 내용 제거
    title = re.sub(r"[|/·…].*$", "", title)         # 구분자 이후 제거
    title = re.sub(r"\s+", " ", title).strip()
    return title.lower()


def _extract_keywords(title: str) -> set[str]:
    """제목에서 키워드를 추출한다 (한국어 + 영문)."""
    title = _normalize_title(title)
    korean = set(re.findall(r"[가-힣]{2,}", title))
    english = set(re.findall(r"[a-z]{2,}", title))
    return korean | english


def _title_similarity(a: str, b: str) -> float:
    """Jaccard 키워드 유사도를 계산한다."""
    kw_a = _extract_keywords(a)
    kw_b = _extract_keywords(b)
    if not kw_a or not kw_b:
        return 0.0
    return len(kw_a & kw_b) / len(kw_a | kw_b)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

_TOPIC_CLUSTER_PROMPT = """\
아래는 이번 주 수집된 뉴스 기사 목록입니다. 각 기사에는 ref_id(인용 번호)가 있습니다.

의미적으로 같은 주제를 다루는 기사들을 토픽으로 묶어주세요.

규칙:
- 토픽은 2개 이상의 기사가 있어야 합니다
- 하나의 기사가 여러 토픽에 속할 수 있습니다
- 토픽 라벨은 한국어로, 내러티브 형태로 작성 (예: "미-이란 전쟁 확대와 유가 충격")
- 최대 8개 토픽까지
- 토픽에 속하지 않는 기사는 무시

JSON 배열로만 응답하세요. 다른 텍스트 없이 JSON만:
[
  {
    "topic": "토픽 라벨",
    "ref_ids": [1, 3, 7, 12],
    "summary": "이 토픽을 한 문장으로 설명"
  }
]

기사 목록:
"""


def _cluster_topics(articles: list[dict]) -> list[dict]:
    """Claude CLI로 기사를 토픽별로 클러스터링한다."""
    claude_path = shutil.which("claude")
    if not claude_path:
        logger.info("  토픽 클러스터링 스킵: Claude CLI 없음")
        return []

    # 기사 목록을 간결하게 구성 (ref_id + 제목 + 요약 앞 100자)
    lines = []
    for a in articles:
        ref_id = a.get("ref_id", 0)
        title = a.get("title", "")
        content_preview = a.get("content", "")[:100]
        lines.append(f"[{ref_id}] {title} — {content_preview}")

    article_list = "\n".join(lines)
    prompt = _TOPIC_CLUSTER_PROMPT + article_list

    logger.info("  토픽 클러스터링 시작 (Claude CLI)...")
    try:
        result = subprocess.run(
            [claude_path, "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=PROJECT_ROOT,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.info("  토픽 클러스터링 실패: %s", e)
        return []

    if result.returncode != 0:
        logger.info("  토픽 클러스터링 실패: exit code %d", result.returncode)
        return []

    # JSON 파싱 (응답에서 JSON 배열 추출)
    output = result.stdout.strip()
    try:
        # JSON 블록 추출 (```json ... ``` 또는 순수 JSON)
        json_match = re.search(r"\[[\s\S]*\]", output)
        if json_match:
            topics = json.loads(json_match.group())
            # 유효성 검증
            valid_ref_ids = {a["ref_id"] for a in articles}
            validated = []
            for t in topics:
                if not isinstance(t, dict):
                    continue
                refs = [r for r in t.get("ref_ids", []) if r in valid_ref_ids]
                if len(refs) >= 2:
                    validated.append({
                        "topic": t.get("topic", ""),
                        "ref_ids": refs,
                        "summary": t.get("summary", ""),
                    })
            return validated
    except (json.JSONDecodeError, KeyError) as e:
        logger.info("  토픽 클러스터링 파싱 실패: %s", e)

    return []


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python preprocessor.py <input.json> <output.json>")
        sys.exit(1)
    preprocess(sys.argv[1], sys.argv[2])
