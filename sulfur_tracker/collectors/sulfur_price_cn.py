"""Tier 1 - China sulfur spot price from tradingeconomics.com (CNY/t). Daily-ish.
The single most responsive free price signal; higher = tightening."""
from __future__ import annotations

from sulfur_tracker.collectors._tradingeconomics import parse_te_headline
from sulfur_tracker.collectors.base import BaseCollector, CollectResult, http_get, staleness_days
from sulfur_tracker.signal import Confidence, Direction, Signal

URL = "https://tradingeconomics.com/commodity/sulfur"


class SulfurPriceCN(BaseCollector):
    name = "sulfur_price_cn"
    source = "tradingeconomics"
    fast = True

    def parse(self, html: str) -> Signal:
        h = parse_te_headline(html, "sulfur")
        direction = (Direction.TIGHTENING.value if (h.change_pct or 0) > 0
                     else Direction.EASING.value if (h.change_pct or 0) < 0
                     else Direction.NEUTRAL.value)
        return Signal(
            source=self.source, metric="sulfur_price_cn", value=h.value,
            unit=h.unit, timestamp=h.date_iso, direction_vs_baseline=direction,
            confidence=Confidence.HIGH.value,
            staleness_days=staleness_days(h.date_iso),
        )

    def collect(self) -> CollectResult:
        url = self.cfg.get("url", URL)
        resp = http_get(url, min_interval=self.cfg.get("min_interval", 2.0))
        signals = [self.parse(resp.text)]
        h = parse_te_headline(resp.text, "sulfur")
        if h.yoy_pct is not None:  # % vs a year ago, straight from the TE blurb
            signals.append(Signal(
                self.source, "sulfur_price_cn_yoy_pct", h.yoy_pct, "%", h.date_iso,
                Direction.TIGHTENING.value if h.yoy_pct > 0 else Direction.EASING.value,
                Confidence.HIGH.value, staleness_days(h.date_iso)))
        return CollectResult(signals=signals)
