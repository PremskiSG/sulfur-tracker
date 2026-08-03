"""Full partner breakdown of sulfur (HS 2503) trade for one reporter/flow/month, from the
free UN Comtrade preview. Reuses the agg_rows dedup so partner sums don't double-count.
Browse-only data (not a scored signal) — feeds the dashboard's Trade flows section.
"""
from __future__ import annotations

import logging
import time

import requests

from sulfur_tracker.collectors.base import http_get
from sulfur_tracker.collectors.indonesia_imports import API, HS_SULFUR, agg_rows

log = logging.getLogger("sulfur_tracker.flows")


def fetch_flows(reporter: int, flow: str, period: str, retries: int = 2,
                min_interval: float = 1.5) -> dict[int, float]:
    """Return {partner_code: kt} for a single month (partners only; the World row 0 is
    dropped). Retries past transient 429s. Empty dict if the month has no usable data."""
    params = {"reporterCode": reporter, "period": period, "cmdCode": HS_SULFUR,
              "flowCode": flow}
    for attempt in range(retries + 1):
        try:
            resp = http_get(API, params=params, min_interval=min_interval)
            break
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status == 429 and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    else:  # pragma: no cover
        return {}

    out: dict[int, float] = {}
    for r in agg_rows(resp.json()):
        pc = r.get("partnerCode")
        wgt = r.get("netWgt") or 0
        if pc in (0, None) or not wgt:
            continue
        out[pc] = out.get(pc, 0.0) + wgt / 1_000_000.0  # kg -> kt
    return {k: round(v, 1) for k, v in out.items()}
