"""Markdown report writer for each headline run."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sulfur_tracker import db
from sulfur_tracker.paths import reports_dir
from sulfur_tracker.scoring import ScoreResult

ZONE_LABEL = {
    "acute": "ACUTE tightening",
    "tightening": "TIGHTENING",
    "stable": "STABLE",
    "easing": "EASING",
    "acute-easing": "ACUTE easing",
}


def _gauge_bar(composite: float, width: int = 41) -> str:
    """ASCII gauge from -100 (left) to +100 (right) with a marker at composite."""
    pos = int(round((composite + 100) / 200 * (width - 1)))
    pos = max(0, min(width - 1, pos))
    cells = ["-"] * width
    cells[width // 2] = "|"
    cells[pos] = "#"
    return "".join(cells)


def render(result: ScoreResult, conn=None) -> str:
    today = date.today().isoformat()
    lines = [
        f"# Sulfur Tracker - {today}",
        "",
        f"**Composite: {result.composite:+.1f}  ({ZONE_LABEL.get(result.zone, result.zone)})**",
        "",
        "```",
        f"easing {_gauge_bar(result.composite)} tightening",
        f"       -100            0            +100   = {result.composite:+.1f}",
        "```",
        "",
        f"- Coverage: **{result.coverage_pct:.0f}%** of weighted signals",
        f"- Max staleness: **{result.max_staleness_days} days**",
    ]
    if result.contamination_flag:
        lines += ["", f"> :warning: **Contamination check:** {result.contamination_flag}"]

    if result.groups:
        lines += ["", "## Where it's coming from", "",
                  "| Group | Contribution | Signals |", "|---|---|---|"]
        for g in result.groups:
            lines.append(f"| {g.label} | {g.contribution:+.1f} | {g.signals} |")

    from sulfur_tracker.signal import GROUPS
    lines += ["", "## Signals", "",
              "| Signal | Group | Value | Dir | z (norm) | Contrib | Points | Stale (d) | Conf |",
              "|---|---|---|---|---|---|---|---|---|"]
    order = {k: v[0] for k, v in GROUPS.items()}
    for s in sorted(result.signals, key=lambda x: (order.get(x.group, 9), -abs(x.contribution))):
        glabel = GROUPS.get(s.group, (0, s.group))[1]
        if s.available:
            val = f"{s.value:g} {s.unit}"
            stale = f"{s.staleness_days}{'!' if s.stale else ''}"
            lines.append(
                f"| {s.label} | {glabel} | {val} | {s.direction} | {s.z:+.2f} | "
                f"{s.contribution:+.2f} | {s.points} | {stale} | {s.confidence} |")
        else:
            lines.append(
                f"| {s.label} | {glabel} | _no data_ | - | - | - | 0 | - | n/a |")

    if conn is not None:
        news = db.recent_news(conn, 21)
        if news:
            lines += ["", "## Recent headlines (21d)", ""]
            for n in news[:15]:
                tag = n["classification"]
                lines.append(f"- [{tag}] [{n['headline']}]({n['url']})")

    lines += ["", "---", "_Bi-weekly headline. Positive = tightening. "
              "Manual/stale signals are flagged; the composite recomputes from whatever "
              "is available._", ""]
    return "\n".join(lines)


def write_report(result: ScoreResult, conn=None) -> Path:
    reports_dir().mkdir(parents=True, exist_ok=True)
    path = reports_dir() / f"{date.today().isoformat()}.md"
    path.write_text(render(result, conn), encoding="utf-8")
    return path
