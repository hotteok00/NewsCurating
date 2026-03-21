"""YAML/JSON 파일 기반 소스 어댑터."""

from pathlib import Path

import yaml

from . import register


@register("file")
def load_file_sources(config: dict) -> list[dict]:
    """sources.yaml 파일에서 URL 목록을 가져온다."""
    sources_file = config.get("sources_file", "sources.yaml")
    path = Path(sources_file)
    if not path.exists():
        raise FileNotFoundError(f"소스 파일을 찾을 수 없습니다: {sources_file}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    entries = data.get("sources", [])
    target_categories = config.get("target_categories")
    if target_categories:
        target_lower = {c.lower() for c in target_categories}
        entries = [e for e in entries if e.get("category", "").lower() in target_lower]

    bookmarks = []
    for entry in entries:
        if not entry.get("enabled", True):
            continue
        bookmarks.append({
            "url": entry["url"],
            "title": entry.get("title", ""),
            "folder": entry.get("category", ""),
        })

    return bookmarks
