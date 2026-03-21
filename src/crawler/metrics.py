"""크롤링 성능 측정."""

import json
import time
from datetime import date
from pathlib import Path
from threading import Lock


class BaseMetrics:
    """메트릭 공통 기반 클래스."""

    def save_to_file(self, data: dict, path: str) -> None:
        """메트릭을 JSON Lines 형식으로 누적 저장한다."""
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        print(f"메트릭 저장: {filepath}")


class CrawlMetrics(BaseMetrics):
    """크롤링 병목 측정."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.phase1_start: float = 0
        self.phase1_end: float = 0
        self.phase2_start: float = 0
        self.web_end: float = 0
        self.yt_end: float = 0
        self.web_count: int = 0
        self.web_ok: int = 0
        self.yt_count: int = 0
        self.yt_ok: int = 0
        self.yt_fail: int = 0

    def inc_web(self, ok: bool = True) -> None:
        with self._lock:
            self.web_count += 1
            if ok:
                self.web_ok += 1

    def inc_yt(self, ok: bool = True) -> None:
        with self._lock:
            self.yt_count += 1
            if ok:
                self.yt_ok += 1
            else:
                self.yt_fail += 1

    def _calc_durations(self) -> dict:
        """Phase별 소요 시간을 계산한다."""
        p1 = self.phase1_end - self.phase1_start
        web_dur = self.web_end - self.phase2_start
        yt_dur = self.yt_end - self.phase2_start
        p2 = max(self.web_end, self.yt_end) - self.phase2_start
        total = max(self.web_end, self.yt_end) - self.phase1_start
        bottleneck = "YouTube" if yt_dur > web_dur else "웹 크롤링"
        idle = abs(yt_dur - web_dur)
        return {
            "p1": p1,
            "web_dur": web_dur,
            "yt_dur": yt_dur,
            "p2": p2,
            "total": total,
            "bottleneck": bottleneck,
            "idle": idle,
        }

    def to_dict(self) -> dict:
        """메트릭을 딕셔너리로 변환한다."""
        d = self._calc_durations()
        return {
            "date": date.today().isoformat(),
            "phase1_duration": round(d["p1"], 1),
            "phase2_duration": round(d["p2"], 1),
            "web_duration": round(d["web_dur"], 1),
            "yt_duration": round(d["yt_dur"], 1),
            "total_duration": round(d["total"], 1),
            "web_count": self.web_count,
            "web_ok": self.web_ok,
            "yt_count": self.yt_count,
            "yt_ok": self.yt_ok,
            "yt_fail": self.yt_fail,
            "bottleneck": d["bottleneck"],
            "article_count": self.web_count + self.yt_count,
        }

    def save_to_file(self, path: str = "logs/metrics.jsonl") -> None:
        """메트릭을 JSON Lines 형식으로 누적 저장한다."""
        super().save_to_file(self.to_dict(), path)

    def report(self) -> str:
        """성능 측정 결과를 포맷된 문자열로 반환한다."""
        d = self._calc_durations()

        lines = [
            "╔══════════════════════════════════════════╗",
            "║         크롤링 성능 측정 결과            ║",
            "╠══════════════════════════════════════════╣",
            f"║ Phase 1 (메타데이터): {d['p1']:6.1f}초              ║",
            f"║ Phase 2 (본문수집):   {d['p2']:6.1f}초              ║",
            f"║   ├─ 웹 크롤링:      {d['web_dur']:6.1f}초 ({self.web_ok}/{self.web_count}건) ║",
            f"║   └─ 유튜브 자막:    {d['yt_dur']:6.1f}초 ({self.yt_ok}/{self.yt_count}건) ║",
            f"║ 전체 소요:           {d['total']:6.1f}초              ║",
            "╠══════════════════════════════════════════╣",
            f"║ 병목: {d['bottleneck']:<10s} (유휴 {d['idle']:.1f}초)       ║",
            f"║ 유튜브 실패: {self.yt_fail}건                     ║",
            "╚══════════════════════════════════════════╝",
        ]
        return "\n".join(lines)


class PipelineMetrics(BaseMetrics):
    """파이프라인 각 단계별 실행시간 측정."""

    def __init__(self) -> None:
        self.steps: list[dict] = []

    def measure(self, name: str) -> "_StepTimer":
        """컨텍스트 매니저로 단계 시간 측정."""
        return _StepTimer(self, name)

    def report(self) -> str:
        total = sum(s["duration"] for s in self.steps)
        lines = [
            "",
            "╔══════════════════════════════════════════════╗",
            "║          파이프라인 실행시간 측정            ║",
            "╠══════════════════════════════════════════════╣",
        ]
        for s in self.steps:
            pct = (s["duration"] / total * 100) if total > 0 else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            lines.append(
                f"║ {s['name']:<14s} {s['duration']:6.1f}초 {bar} {pct:4.1f}% ║"
            )
        lines.append("╠══════════════════════════════════════════════╣")
        lines.append(f"║ {'총 소요시간':<14s} {total:6.1f}초 ({total/60:.1f}분)          ║")
        lines.append("╚══════════════════════════════════════════════╝")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "date": date.today().isoformat(),
            "steps": {s["name"]: round(s["duration"], 1) for s in self.steps},
            "total": round(sum(s["duration"] for s in self.steps), 1),
        }

    def save_to_file(self, path: str = "logs/pipeline_metrics.jsonl") -> None:
        """메트릭을 JSON Lines 형식으로 누적 저장한다."""
        super().save_to_file(self.to_dict(), path)

    # main.py 호환 별칭
    save = save_to_file


class _StepTimer:
    def __init__(self, metrics: PipelineMetrics, name: str) -> None:
        self.metrics = metrics
        self.name = name

    def __enter__(self) -> "_StepTimer":
        self.start = time.time()
        return self

    def __exit__(self, *args: object) -> None:
        duration = time.time() - self.start
        self.metrics.steps.append({"name": self.name, "duration": duration})
