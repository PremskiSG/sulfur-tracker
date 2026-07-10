"""RSS/keyword scan of free mining & commodity headlines. No LLM: a simple keyword rule
set tags each relevant hit tightening/easing/neutral. This is NOT a scored signal — it
only stores headlines so the contamination check can see whether curtailments are being
reported. (The old net-tightening score was dropped.)

Sources are free RSS only (Reuters/Argus/S&P feeds are blocked, so they're dropped in
favour of mining.com + Google News queries + Kitco).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from sulfur_tracker.collectors.base import (BaseCollector, CollectResult, NewsItem,
                                            http_get, now_iso)
from sulfur_tracker.signal import Confidence, Direction, Signal

DEFAULT_FEEDS = [
    "https://www.mining.com/feed/",
    "https://news.google.com/rss/search?q=%22sulphur%22+OR+%22HPAL%22+nickel&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Hormuz+sulphur+OR+phosphate&hl=en-US&gl=US&ceid=US:en",
]

# A headline only counts if it is topically relevant to the sulfur chain.
TOPIC_TERMS = ["sulphur", "sulfur", "hpal", "nickel", "mhp", "phosphate", "ocp",
               "mosaic", "jorf lasfar", "hormuz", "morowali", "weda bay"]

TIGHTENING_TERMS = ["curtailment", "care and maintenance", "force majeure", "shortage",
                    "supply disruption", "output cut", "suspend", "halt", "shut",
                    "tighten", "disruption", "export ban", "blockade"]
EASING_TERMS = ["restart", "resume", "ramp up", "ramp-up", "surplus", "oversupply",
                "ease", "eases", "recovery", "resumes", "restarts", "glut"]


def classify(headline: str) -> tuple[str, list[str]]:
    text = headline.lower()
    if not any(t in text for t in TOPIC_TERMS):
        return Direction.NEUTRAL.value, []
    matched = [t for t in TIGHTENING_TERMS if t in text]
    eased = [t for t in EASING_TERMS if t in text]
    if len(matched) > len(eased):
        return Direction.TIGHTENING.value, matched
    if len(eased) > len(matched):
        return Direction.EASING.value, eased
    return Direction.NEUTRAL.value, matched + eased


def _parse_pubdate(raw: str | None) -> str:
    if raw:
        try:
            return parsedate_to_datetime(raw).astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            pass
    return now_iso()


def parse_feed(xml_text: str, source: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        cls, matched = classify(title)
        if cls == Direction.NEUTRAL.value and not matched:
            continue  # skip off-topic headlines entirely
        items.append(NewsItem(
            ts=_parse_pubdate(item.findtext("pubDate")), source=source,
            headline=title, url=link, classification=cls,
            matched_keywords=",".join(matched),
        ))
    return items


class NewsMonitor(BaseCollector):
    name = "news_monitor"
    source = "news_rss"
    fast = True

    def collect(self) -> CollectResult:
        feeds = self.cfg.get("feeds", DEFAULT_FEEDS)
        max_age = int(self.cfg.get("max_age_days", 30))
        cutoff = now_iso()  # compared lexically against ISO ts below
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        news: list[NewsItem] = []
        for url in feeds:
            try:
                resp = http_get(url, min_interval=self.cfg.get("min_interval", 1.5))
                # Google News search RSS returns by relevance, not recency, so drop
                # anything older than max_age_days to keep the signal current.
                news.extend(n for n in parse_feed(resp.text, url) if n.ts >= cutoff)
            except Exception:  # noqa: BLE001 - one bad feed shouldn't sink the rest
                continue
        # No longer a scored signal — news_monitor exists only to store headlines that
        # the contamination check reads (curtailment keywords within its window).
        tight = sum(1 for n in news if n.classification == Direction.TIGHTENING.value)
        note = (f"{len(news)} headlines ({tight} tightening) stored for contamination check"
                if news else "no headlines matched")
        return CollectResult(signals=[], news=news, note=note)
