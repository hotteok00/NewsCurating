import tempfile
import unittest
from datetime import timezone
from pathlib import Path
from unittest import mock

from feedparser import FeedParserDict

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from crawler.handlers import _scrape_limited_list
from crawler.rss import _parse_feed_date
from crawler.utils import set_runtime_crawl_options
from llm_reporter import generate_report
from preprocessor import _to_slim
from report_generator import _build_html


class RegressionTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_runtime_crawl_options({})

    def test_preprocessor_prefers_summary_and_respects_max_length(self) -> None:
        article = {
            "url": "https://example.com/article",
            "title": "Example title",
            "summary": "짧은 요약문",
            "content": "아주 긴 본문 " * 100,
            "date": "2026-03-16",
            "source_group": "Trend",
        }

        slim = _to_slim(article, max_summary_length=20)

        self.assertEqual(slim["content"], "짧은 요약문")

        article["summary"] = ""
        slim = _to_slim(article, max_summary_length=20)
        self.assertLessEqual(len(slim["content"]), 20)
        self.assertTrue(slim["content"].endswith("..."))

    def test_interactive_html_includes_base_and_interactive_css(self) -> None:
        html = _build_html(
            "<h1>Title</h1>",
            "body{color:red;}",
            interactive=True,
            interactive_css=".search-box{color:blue;}",
            interactive_js="console.log('ok')",
        )

        self.assertIn("body{color:red;}", html)
        self.assertIn(".search-box{color:blue;}", html)
        self.assertIn("console.log('ok')", html)

    def test_parse_feed_date_keeps_timezone_offset(self) -> None:
        entry = FeedParserDict({"published": "2026-03-16T12:00:00-04:00"})

        parsed = _parse_feed_date(entry)

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.hour, 16)

    def test_generate_report_fails_gracefully_when_claude_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            slim_file = tmp / "sample.json"
            slim_file.write_text("[]", encoding="utf-8")
            output_file = tmp / "out.md"
            template_file = tmp / "template.txt"
            template_file.write_text(
                "Read {slim_file} and write {md_file}.{feedback_prompt}",
                encoding="utf-8",
            )

            with mock.patch("llm_reporter.shutil.which", return_value=None):
                ok = generate_report(
                    str(slim_file),
                    str(output_file),
                    template=str(template_file),
                )

        self.assertFalse(ok)

    def test_runtime_max_articles_setting_is_used(self) -> None:
        set_runtime_crawl_options({"max_articles_per_source": 2})

        articles = _scrape_limited_list(
            [
                ("https://example.com/1", "Title One Long"),
                ("https://example.com/2", "Title Two Long"),
                ("https://example.com/3", "Title Three Long"),
            ],
            "https://source.example.com",
            "Trend",
        )

        self.assertEqual(len(articles), 2)


if __name__ == "__main__":
    unittest.main()
