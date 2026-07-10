"""Shared parser for tradingeconomics.com commodity pages.

TE server-renders a headline sentence like:
    "Sulfur fell to 8,569 CNY/T on July 8, 2026, down 11.21% ..."
    "Nickel rose to 16,538.50 USD/T on July 9, 2026, up 0.72% ..."
We parse the value, unit and date from that sentence -- robust to layout changes
because it does not depend on any specific CSS/DOM node.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

_HEADLINE = re.compile(
    r"([A-Za-z]+)\s+(rose|fell|increased|decreased|traded|was|climbed|dropped|"
    r"jumped|declined)\s+(?:to|around|at)\s+\$?([\d,]+(?:\.\d+)?)\s*"
    r"([A-Z]{3})/(?:T|MT|Tonne)\s+on\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
_CHANGE = re.compile(r"\b(up|down)\s+([\d.]+)%")
_YOY = re.compile(r"([\d.]+)%\s+(higher|lower)\s+than a year ago", re.IGNORECASE)


@dataclass
class TEHeadline:
    commodity: str
    value: float
    unit: str            # e.g. "CNY/t"
    date_iso: str        # observation date YYYY-MM-DD
    change_pct: float | None
    yoy_pct: float | None = None   # % vs a year ago, from the TE blurb


def parse_te_headline(html: str, commodity: str) -> TEHeadline:
    for m in _HEADLINE.finditer(html):
        if m.group(1).lower() != commodity.lower():
            continue
        value = float(m.group(3).replace(",", ""))
        currency = m.group(4).upper()
        date_iso = datetime.strptime(m.group(5), "%B %d, %Y").strftime("%Y-%m-%d")
        tail = html[m.end():m.end() + 60]
        cm = _CHANGE.search(tail)
        change = None
        if cm:
            change = float(cm.group(2)) * (1 if cm.group(1).lower() == "up" else -1)
        ym = _YOY.search(html[m.start():m.start() + 400])
        yoy = None
        if ym:
            yoy = float(ym.group(1)) * (1 if ym.group(2).lower() == "higher" else -1)
        return TEHeadline(commodity, value, f"{currency}/t", date_iso, change, yoy)
    raise ValueError(f"tradingeconomics headline for {commodity!r} not found")
