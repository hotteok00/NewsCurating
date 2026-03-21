"""크롤링 메트릭 대시보드 생성기.

logs/metrics.jsonl을 읽어서 standalone HTML 대시보드를 생성한다.
Chart.js CDN을 사용하여 그래프를 렌더링한다.
"""

import json
from pathlib import Path
from string import Template

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# 병목 구간 이름 → CSS 클래스 접미사 매핑
BOTTLENECK_CSS_CLASS = {
    "youtube": "youtube",
    "유튜브": "youtube",
    "web": "web",
    "웹크롤링": "web",
    "웹 크롤링": "web",
}


def _calc_success_rate(ok: int, count: int) -> float:
    """성공 건수와 전체 건수로 성공률(%)을 계산한다.

    Args:
        ok: 성공 건수
        count: 전체 건수

    Returns:
        성공률 (0~100), 전체 건수가 0이면 0을 반환
    """
    if count > 0:
        return round(ok / count * 100, 1)
    return 0


def _bottleneck_badge_class(bottleneck: str) -> str:
    """병목 구간 이름에 대응하는 CSS badge 클래스 접미사를 반환한다."""
    key = bottleneck.lower().replace(" ", "")
    return BOTTLENECK_CSS_CLASS.get(key, BOTTLENECK_CSS_CLASS.get(bottleneck.lower(), "web"))


def load_metrics(path: str = "logs/metrics.jsonl") -> list[dict]:
    """JSON Lines 파일에서 메트릭을 로드한다."""
    filepath = Path(path)
    if not filepath.exists():
        return []
    metrics = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                metrics.append(json.loads(line))
    return metrics


def generate_dashboard(
    metrics: list[dict],
    output_path: str = "reports/dashboard.html",
) -> str:
    """메트릭 데이터로 HTML 대시보드를 생성한다."""
    if not metrics:
        print("메트릭 데이터가 없습니다.")
        return ""

    dates = [m["date"] for m in metrics]
    phase1 = [m["phase1_duration"] for m in metrics]
    phase2 = [m["phase2_duration"] for m in metrics]
    web_dur = [m["web_duration"] for m in metrics]
    yt_dur = [m["yt_duration"] for m in metrics]
    total_dur = [m["total_duration"] for m in metrics]
    web_ok = [m["web_ok"] for m in metrics]
    web_count = [m["web_count"] for m in metrics]
    yt_ok = [m["yt_ok"] for m in metrics]
    yt_count = [m["yt_count"] for m in metrics]
    article_count = [m["article_count"] for m in metrics]

    # 성공률 계산
    web_rate = [
        _calc_success_rate(ok, cnt) for ok, cnt in zip(web_ok, web_count)
    ]
    yt_rate = [
        _calc_success_rate(ok, cnt) for ok, cnt in zip(yt_ok, yt_count)
    ]

    # 최근 실행 요약
    latest = metrics[-1]
    web_success_pct = _calc_success_rate(latest["web_ok"], latest["web_count"])
    yt_success_pct = _calc_success_rate(latest["yt_ok"], latest["yt_count"])

    # 테이블 행 생성 (역순)
    table_rows = ""
    for m in reversed(metrics):
        w_pct = _calc_success_rate(m["web_ok"], m["web_count"])
        y_pct = _calc_success_rate(m["yt_ok"], m["yt_count"])
        badge_cls = _bottleneck_badge_class(m["bottleneck"])
        table_rows += f"""
            <tr>
                <td>{m["date"]}</td>
                <td>{m["total_duration"]}s</td>
                <td>{m["phase1_duration"]}s</td>
                <td>{m["web_duration"]}s</td>
                <td>{m["yt_duration"]}s</td>
                <td>{m["web_ok"]}/{m["web_count"]} ({w_pct}%)</td>
                <td>{m["yt_ok"]}/{m["yt_count"]} ({y_pct}%)</td>
                <td>{m["article_count"]}</td>
                <td><span class="badge badge-{badge_cls}">{m["bottleneck"]}</span></td>
            </tr>"""

    # 템플릿 파일 로드
    template_path = PROJECT_ROOT / "templates" / "dashboard.html"
    if not template_path.exists():
        print(f"대시보드 템플릿을 찾을 수 없습니다: {template_path}")
        return ""

    tpl = Template(template_path.read_text(encoding="utf-8"))
    html = tpl.safe_substitute(
        metrics_count=len(metrics),
        latest_total_duration=latest["total_duration"],
        web_success_pct=web_success_pct,
        yt_success_pct=yt_success_pct,
        latest_article_count=latest["article_count"],
        latest_bottleneck=latest["bottleneck"],
        table_rows=table_rows,
        dates_json=json.dumps(dates),
        total_dur_json=json.dumps(total_dur),
        web_dur_json=json.dumps(web_dur),
        yt_dur_json=json.dumps(yt_dur),
        web_rate_json=json.dumps(web_rate),
        yt_rate_json=json.dumps(yt_rate),
        phase1_json=json.dumps(phase1),
        phase2_json=json.dumps(phase2),
        latest_web_duration=latest["web_duration"],
        latest_yt_duration=latest["yt_duration"],
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"대시보드 생성: {out}")
    return str(out)


def main() -> None:
    """CLI 진입점."""
    import argparse

    parser = argparse.ArgumentParser(description="크롤링 메트릭 대시보드 생성")
    parser.add_argument(
        "--metrics", default="logs/metrics.jsonl", help="메트릭 JSONL 파일 경로"
    )
    parser.add_argument(
        "--output", default="reports/dashboard.html", help="대시보드 HTML 출력 경로"
    )
    args = parser.parse_args()

    metrics = load_metrics(args.metrics)
    if not metrics:
        print(f"메트릭 파일을 찾을 수 없거나 비어 있습니다: {args.metrics}")
        return

    print(f"메트릭 {len(metrics)}개 로드됨")
    path = generate_dashboard(metrics, args.output)
    if path:
        print(f"대시보드를 브라우저에서 열어보세요: {path}")


if __name__ == "__main__":
    main()
