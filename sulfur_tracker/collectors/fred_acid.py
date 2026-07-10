"""FRED US Producer Price Index: Sulfuric Acid (WPU0613020T1) — a free, monthly, decades-
long index of US sulfuric-acid prices. Reference series (not scored): shows the long-run
US acid trend that the Tampa / Itafos phosphate channel sits in.

Uses the free FRED API when a key is present (secrets.yaml `fred.api_key` or FRED_API_KEY),
falling back to the public CSV download. Degrades cleanly if neither is reachable.
"""
from __future__ import annotations

import csv
import io

from sulfur_tracker.collectors.base import (BaseCollector, CollectResult, http_get,
                                            staleness_days)
from sulfur_tracker.secrets import get_secret
from sulfur_tracker.signal import Confidence, Direction, Signal

SERIES = "WPU0613020T1"
API = "https://api.stlouisfed.org/fred/series/observations"
CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def parse_csv(text: str, series: str = SERIES) -> list[tuple[str, float]]:
    """(date, value) pairs from a FRED CSV export, oldest first."""
    out: list[tuple[str, float]] = []
    for row in csv.DictReader(io.StringIO(text)):
        date = row.get("DATE") or row.get("observation_date")
        val = row.get(series)
        if val is None:  # single-series CSV: take the one non-date column
            others = [v for k, v in row.items() if k not in ("DATE", "observation_date")]
            val = others[0] if others else None
        if not date or val in (None, ".", ""):
            continue
        try:
            out.append((date, float(val)))
        except ValueError:
            continue
    return out


def fetch_observations(series: str = SERIES, cfg: dict | None = None) -> list[tuple[str, float]]:
    cfg = cfg or {}
    key = get_secret("fred", "api_key", env_var="FRED_API_KEY")
    if key:
        resp = http_get(cfg.get("api", API), min_interval=1.0,
                        params={"series_id": series, "api_key": key, "file_type": "json"})
        out: list[tuple[str, float]] = []
        for r in resp.json().get("observations") or []:
            v = r.get("value")
            if v in (None, ".", ""):
                continue
            try:
                out.append((r["date"], float(v)))
            except (ValueError, KeyError):
                continue
        return out
    # No key -> public CSV download.
    resp = http_get(cfg.get("csv", CSV), params={"id": series}, min_interval=1.0)
    return parse_csv(resp.text, series)


class FredAcid(BaseCollector):
    name = "fred_acid"
    source = "fred"
    fast = False

    def collect(self) -> CollectResult:
        obs = fetch_observations(self.cfg.get("series", SERIES), self.cfg)
        if not obs:
            return CollectResult(note="no FRED data (needs FRED key or network)")
        date, val = obs[-1]
        sig = Signal(self.source, "fred_acid_ppi", val, "index", date,
                     Direction.NEUTRAL.value, Confidence.HIGH.value, staleness_days(date))
        return CollectResult(signals=[sig], note=f"latest {date} = {val}")
