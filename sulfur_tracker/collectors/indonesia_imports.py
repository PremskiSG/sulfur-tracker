"""Tier 1 - Indonesian sulfur imports (HS 2503) from the free UN Comtrade v1 preview
API. Comtrade lags ~2 months, allows one period per preview call, and the free preview
endpoint is flaky (intermittent 429s, months that report near-zero). A trailing-3-month
SUM is therefore unstable -- one missing month swings it by a third. So we report the
latest available MONTH's import volume (kt): we scan back from the lag anchor to the
most recent month with real data, retrying past 429s. Higher imports = easing.
"""
from __future__ import annotations

import calendar
import time
from datetime import date

import requests

from sulfur_tracker.collectors.base import BaseCollector, CollectResult, http_get, staleness_days
from sulfur_tracker.signal import Confidence, Direction, Signal

API = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
REPORTER_INDONESIA = 360
HS_SULFUR = 2503


def world_kt(payload: dict) -> float | None:
    """Extract net import weight in kt from a single-period Comtrade response.

    The free preview endpoint is inconsistent: some months carry a World aggregate
    row (partnerCode 0) with netWgt, others report netWgt=0/None on that row while the
    per-partner rows carry the weight. So we prefer the World row only when it has a
    positive weight, and otherwise sum the individual partner rows.
    """
    rows = agg_rows(payload)
    if not rows:
        return None
    world = next((r for r in rows if r.get("partnerCode") == 0), None)
    total = (world.get("netWgt") or 0) if world else 0
    if not total:  # World row missing or zero -> sum partners (exclude any World row)
        total = sum((r.get("netWgt") or 0) for r in rows if r.get("partnerCode") != 0)
    if not total:
        return None
    return round(total / 1_000_000.0, 1)  # kg -> kt


def agg_rows(payload: dict) -> list[dict]:
    """Comtrade repeats each partner once per mode-of-transport *plus* an all-modes
    aggregate (motCode 0). Keep only the aggregate or every total double-counts."""
    rows = payload.get("data") or []
    agg = [r for r in rows if r.get("motCode") in (0, None)]
    return agg or rows


def _shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = (y * 12 + (m - 1)) + delta
    return idx // 12, idx % 12 + 1


def _months_back(anchor: date, n: int) -> list[str]:
    out = []
    y, m = anchor.year, anchor.month
    for i in range(n):
        yy, mm = _shift_month(y, m, -i)
        out.append(f"{yy}{mm:02d}")
    return out


class ComtradeMonthlyImports(BaseCollector):
    """Latest available monthly HS-2503 import volume (kt) for one reporter, read from
    the flaky free Comtrade preview with 429 retries. Subclasses set the reporter."""
    name = "comtrade_imports"
    source = "un_comtrade"
    fast = False

    REPORTER = REPORTER_INDONESIA
    METRIC = "indonesia_sulfur_imports_kt"
    UNIT = "kt(mo)"
    EMIT_YOY = True
    YOY_METRIC = "indonesia_imports_yoy_pct"

    def _fetch_period(self, period: str, retries: int = 2) -> float | None:
        """kt for a single YYYYMM period; retries past transient 429s. Returns None
        if the month has no usable data."""
        params = {"reporterCode": self.REPORTER, "period": period,
                  "cmdCode": HS_SULFUR, "flowCode": "M"}
        for attempt in range(retries + 1):
            try:
                resp = http_get(self.cfg.get("api", API), params=params,
                                min_interval=self.cfg.get("min_interval", 2.5))
                return world_kt(resp.json())
            except requests.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status == 429 and attempt < retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise
        return None

    def collect(self) -> CollectResult:
        lag = int(self.cfg.get("lag_months", 2))
        max_lookback = int(self.cfg.get("max_lookback_months", 8))
        today = date.today()
        ay, am = _shift_month(today.year, today.month, -lag)

        latest = None
        for i in range(max_lookback):
            yy, mm = _shift_month(ay, am, -i)
            kt = self._fetch_period(f"{yy}{mm:02d}")
            if kt and kt > 0:
                latest = (yy, mm, kt)
                break
        if latest is None:
            raise ValueError("no recent Comtrade data in lookback window")

        yy, mm, kt = latest
        ts = date(yy, mm, calendar.monthrange(yy, mm)[1]).isoformat()
        signals = [Signal(
            source=self.source, metric=self.METRIC, value=kt,
            unit=self.UNIT, timestamp=ts, direction_vs_baseline=Direction.NEUTRAL.value,
            confidence=Confidence.MEDIUM.value, staleness_days=staleness_days(ts))]

        if self.EMIT_YOY:
            try:
                prior = self._fetch_period(f"{yy - 1}{mm:02d}")
            except Exception:  # noqa: BLE001
                prior = None
            if prior and prior > 0:
                yoy = round(100.0 * (kt - prior) / prior, 1)
                signals.append(Signal(self.source, self.YOY_METRIC, yoy, "%", ts,
                                      Direction.NEUTRAL.value, Confidence.MEDIUM.value,
                                      staleness_days(ts)))
        return CollectResult(signals=signals, note=f"latest month {yy}-{mm:02d}")


class IndonesiaImports(ComtradeMonthlyImports):
    name = "indonesia_imports"
    REPORTER = REPORTER_INDONESIA
    METRIC = "indonesia_sulfur_imports_kt"
    EMIT_YOY = True

# NOTE: China imports (reporter 156) was evaluated as a physical proxy but the free
# Comtrade preview stops reporting China around end-2024 (2025-2026 return empty), so
# it yields no recent trend. Gulf-country sulfur exports are likewise sparse (only Saudi,
# stopping mid-2025). Neither China port stocks nor Gulf departures has a usable free
# recent historical series -- both remain manual-entry by design.
