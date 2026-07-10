"""Monthly LLM price scanner. The official Mideast sulfur prices (Kuwait KSP, Adnoc
OSP) and the sulfuric-acid indexes are announced in trade press but not on a clean
endpoint. This collector pulls recent free news headlines for each and asks DeepSeek to
read the latest announced value out of them — automating what is otherwise manual entry.

Needs a DeepSeek key (secrets.yaml `deepseek.api_key` or DEEPSEEK_API_KEY); with no key
it degrades cleanly to manual entry. Meant to run ~monthly (`tracker scan-prices`).
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from sulfur_tracker import llm
from sulfur_tracker.collectors.base import (BaseCollector, CollectResult, http_get,
                                            now_iso, staleness_days)
from sulfur_tracker.signal import Confidence, Direction, Signal

log = logging.getLogger("sulfur_tracker.collectors")

NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

# metric -> (human label, news query, unit). Sulfuric-acid indexes can be added here
# once tampa_acid / vancouver_acid are wired as signals.
DEFAULT_TARGETS: dict[str, tuple[str, str, str]] = {
    "ksp_fob": ("Kuwait KSP official monthly sulphur selling price",
                "Kuwait sulphur price KSP monthly", "USD/t"),
    "adnoc_osp_fob": ("ADNOC OSP official monthly sulphur selling price",
                      "ADNOC sulphur OSP price monthly", "USD/t"),
    "tampa_sulfur_cfr": ("Tampa molten sulfur quarterly contract price, USD per long ton CFR",
                         "Tampa sulfur contract price CFR quarterly", "USD/lt"),
}

SYSTEM = ("You are a commodities analyst. You read news headlines and extract the most "
          "recent officially-announced price for each requested benchmark. Reply with a "
          "single JSON object and nothing else.")


def _recent_titles(url: str, days: int) -> list[tuple[str, str]]:
    """(title, YYYY-MM-DD) for RSS items within `days`, newest first."""
    try:
        resp = http_get(url, min_interval=1.5)
        root = ET.fromstring(resp.text)
    except Exception as exc:  # noqa: BLE001
        log.warning("news fetch failed for %s: %s", url, exc)
        return []
    cutoff = (datetime.now(timezone.utc).timestamp()) - days * 86400
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        raw = item.findtext("pubDate")
        try:
            dt = parsedate_to_datetime(raw).astimezone(timezone.utc)
        except (TypeError, ValueError):
            dt = datetime.now(timezone.utc)
        if dt.timestamp() >= cutoff:
            out.append((title, dt.strftime("%Y-%m-%d")))
    return out


def _build_prompt(targets: dict, blob: list[str]) -> str:
    keys = "\n".join(f'  "{m}": official {lbl} in USD per tonne'
                     for m, (lbl, _q, _u) in targets.items())
    schema = ", ".join(f'"{m}": {{"price": <number|null>, "date": "<YYYY-MM|null>"}}'
                       for m in targets)
    return (
        "From the sulphur-market headlines below, extract the MOST RECENT officially "
        "announced monthly price for each benchmark:\n" + keys +
        "\n\nRules: price is a number in USD/tonne (strip $ and units). If a headline "
        "gives a month, put it in `date` as YYYY-MM; else null. If you cannot find a "
        "clear official value, use null for that benchmark — do not guess.\n\n"
        "Reply with ONLY this JSON (no prose, no markdown):\n{" + schema + "}\n\n"
        "Headlines:\n" + "\n".join(blob)
    )


def _norm_date(val) -> str:
    if isinstance(val, str):
        if len(val) == 7:            # YYYY-MM -> mid-month
            return val + "-15"
        if len(val) >= 10:
            return val[:10]
    return now_iso()[:10]


class LlmPriceScan(BaseCollector):
    name = "llm_price_scan"
    source = "deepseek"
    fast = False

    def collect(self) -> CollectResult:
        if not llm.has_key():
            return CollectResult(note="no DeepSeek key — use manual entry "
                                      "(tracker input ksp / adnoc_osp)")
        targets = self.cfg.get("targets") or DEFAULT_TARGETS
        lookback = int(self.cfg.get("lookback_days", 120))
        model = self.cfg.get("model", "deepseek-v4-flash")

        blob: list[str] = []
        for metric, (_lbl, query, _unit) in targets.items():
            for title, d in _recent_titles(NEWS_RSS.format(q=quote_plus(query)),
                                           lookback)[:15]:
                blob.append(f"- [{metric}] ({d}) {title}")
        if not blob:
            return CollectResult(note="no headlines found")

        try:
            data = llm.extract(_build_prompt(targets, blob), SYSTEM, model=model)
        except Exception as exc:  # noqa: BLE001
            return CollectResult(note=f"DeepSeek call failed: {exc}")

        signals, unchanged = [], 0
        for metric, (_lbl, _query, unit) in targets.items():
            item = data.get(metric) or {}
            price = item.get("price")
            if price is None:
                continue
            try:
                value = float(str(price).replace(",", "").replace("$", ""))
            except ValueError:
                continue
            ts = _norm_date(item.get("date"))
            if not self._is_new(metric, value, ts):
                unchanged += 1        # weekly run, price hasn't moved -> don't duplicate
                continue
            signals.append(Signal(self.source, metric, value, unit, ts,
                                  Direction.NEUTRAL.value, Confidence.MEDIUM.value,
                                  staleness_days(ts)))
        note = f"{len(signals)} new, {unchanged} unchanged via {model}"
        return CollectResult(signals=signals, note=note)

    def _is_new(self, metric: str, value: float, ts: str) -> bool:
        """Accept a scanned price only if it's genuinely new information: a newer month
        than what we already have, or a correction to the same month. Older or identical
        extractions are skipped, so weekly re-runs never duplicate or regress the series."""
        if self.conn is None:
            return True
        from sulfur_tracker import db
        latest = db.latest_signal(self.conn, metric)
        if latest is None:
            return True
        if ts > latest["ts"]:                       # newer announcement (ISO dates sort)
            return True
        if ts == latest["ts"] and value != latest["value"]:  # correction to same month
            return True
        return False                                # older or identical -> skip
