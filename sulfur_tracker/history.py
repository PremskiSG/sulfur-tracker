"""`tracker history` - backfill REAL historical series so trends are populated on day
one. Two sources have usable free history:

  * UN Comtrade  -> monthly Indonesia sulfur imports (past months are stable, unlike
    the flaky most-recent ones). Zero/near-zero months are data gaps and are skipped.
  * yfinance     -> the anchor equity NCKL.JK (Obi Island), weekly closes.

Prices for sulfur/nickel have no free historical source (TradingEconomics serves them
only via a paid API), so those series accumulate forward from each `tracker run`.
"""
from __future__ import annotations

import calendar
import json
import logging
from datetime import date
from pathlib import Path

from sulfur_tracker import db
from sulfur_tracker.collectors.base import staleness_days
from sulfur_tracker.collectors.indonesia_imports import IndonesiaImports, _shift_month
from sulfur_tracker.signal import Confidence, Direction, Signal

log = logging.getLogger("sulfur_tracker.history")


def _backfill_comtrade(conn, collector, months: int, lag: int = 2,
                       min_kt: float = 5.0) -> int:
    """Fetch monthly HS-2503 volumes for `collector` over the `months` months ending
    `lag` months ago, skipping data-gap months (< min_kt)."""
    run_id = db.start_run(conn, "backfill")
    today = date.today()
    inserted = 0
    for i in range(lag, lag + months):
        yy, mm = _shift_month(today.year, today.month, -i)
        try:
            kt = collector._fetch_period(f"{yy}{mm:02d}")
        except Exception as exc:  # noqa: BLE001
            log.warning("comtrade %s %s%02d failed: %s", collector.METRIC, yy, mm, exc)
            continue
        if not kt or kt < min_kt:
            continue
        ts = date(yy, mm, calendar.monthrange(yy, mm)[1]).isoformat()
        db.insert_signal(conn, run_id, Signal(
            "un_comtrade", collector.METRIC, kt, collector.UNIT, ts,
            Direction.NEUTRAL.value, Confidence.MEDIUM.value, staleness_days(ts)))
        inserted += 1
    db.finish_run(conn, run_id)
    return inserted


def backfill_comtrade(conn, months: int = 18) -> int:
    return _backfill_comtrade(conn, IndonesiaImports({"min_interval": 2.5}), months)


def import_price_json(conn, path: str, metric: str = "sulfur_price_cn") -> int:
    """Import a JSON price-history file (e.g. a TradingEconomics export) as real
    observations for a metric. Supersedes the placeholder seeds and the derived anchor
    for that metric, and is re-runnable (drops any prior import first). Schema:
        {"unit": "CNY/T", "data": [{"date": "YYYY-MM-DD", "price": <float>}, ...]}
    """
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    unit = (payload.get("unit") or "CNY/t").replace("CNY/T", "CNY/t")
    rows = payload.get("data") or []
    conn.execute("DELETE FROM signals WHERE metric=? AND source IN "
                 "('seed', 'te_derived', 'te_history')", (metric,))
    conn.commit()
    run_id = db.start_run(conn, "backfill")
    n = 0
    for r in rows:
        d, p = r.get("date"), r.get("price")
        if not d or p is None:
            continue
        db.insert_signal(conn, run_id, Signal(
            "te_history", metric, float(p), unit, d, Direction.NEUTRAL.value,
            Confidence.HIGH.value, staleness_days(d)))
        n += 1
    db.finish_run(conn, run_id)
    return n


def backfill_sulfur_anchor(conn) -> int:
    """No free source has a full China sulfur price history, but the TradingEconomics
    feed states how much higher the price is than a year ago. We use that to derive one
    honest ~1-year-ago anchor point so the price chart shows the spike. Skipped once a
    real imported history exists. Refreshes in place (source='te_derived')."""
    from datetime import datetime, timedelta

    from sulfur_tracker.collectors._tradingeconomics import parse_te_headline
    from sulfur_tracker.collectors.base import http_get
    have_real = conn.execute(
        "SELECT COUNT(*) c FROM signals WHERE metric='sulfur_price_cn' "
        "AND source='te_history'").fetchone()["c"]
    if have_real:
        return 0
    try:
        resp = http_get("https://tradingeconomics.com/commodity/sulfur", min_interval=2.0)
        h = parse_te_headline(resp.text, "sulfur")
    except Exception as exc:  # noqa: BLE001
        log.warning("sulfur anchor fetch failed: %s", exc)
        return 0
    if h.yoy_pct is None or h.yoy_pct <= -100:
        return 0
    conn.execute("DELETE FROM signals WHERE metric='sulfur_price_cn' "
                 "AND source='te_derived'")
    conn.commit()
    year_ago = (datetime.strptime(h.date_iso, "%Y-%m-%d")
                - timedelta(days=365)).strftime("%Y-%m-%d")
    val = round(h.value / (1 + h.yoy_pct / 100.0), 0)
    run_id = db.start_run(conn, "backfill")
    db.insert_signal(conn, run_id, Signal(
        "te_derived", "sulfur_price_cn", val, "CNY/t", year_ago,
        Direction.NEUTRAL.value, Confidence.MEDIUM.value, staleness_days(year_ago)))
    db.finish_run(conn, run_id)
    return 1


def backfill_fred_acid(conn) -> int:
    """Load the full free FRED sulfuric-acid PPI history (monthly, decades). Refreshes in
    place (source='fred')."""
    from sulfur_tracker.collectors.fred_acid import fetch_observations
    try:
        obs = fetch_observations()
    except Exception as exc:  # noqa: BLE001
        log.warning("FRED backfill failed: %s", exc)
        return 0
    if not obs:
        return 0
    conn.execute("DELETE FROM signals WHERE metric='fred_acid_ppi' AND source='fred'")
    conn.commit()
    run_id = db.start_run(conn, "backfill")
    for date, val in obs:
        db.insert_signal(conn, run_id, Signal(
            "fred", "fred_acid_ppi", val, "index", date, Direction.NEUTRAL.value,
            Confidence.MEDIUM.value, staleness_days(date)))
    db.finish_run(conn, run_id)
    return len(obs)


def backfill_history(conn, months: int = 18) -> dict[str, int]:
    # NCKL.JK anchor history dropped — nickel reference prices are no longer displayed.
    return {
        "indonesia_imports": backfill_comtrade(conn, months=months),
        "sulfur_price_anchor": backfill_sulfur_anchor(conn),
        "fred_acid_ppi": backfill_fred_acid(conn),
    }
