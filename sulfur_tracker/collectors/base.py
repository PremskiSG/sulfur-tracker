"""Collector base class + a polite shared HTTP helper.

Every collector subclasses BaseCollector and implements collect() returning a
CollectResult. safe_run() wraps it so one failing/credential-less collector never
breaks the run -- it logs and returns an empty result, and the composite recomputes
from whatever is available.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from sulfur_tracker.signal import Signal

log = logging.getLogger("sulfur_tracker.collectors")

DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
              "sulfur-tracker/0.1")

_last_hit: dict[str, float] = {}


def http_get(url: str, *, timeout: int = 15, min_interval: float = 1.0,
             headers: dict | None = None, **kw) -> requests.Response:
    """GET with a per-host polite rate limit, a browser-ish UA and raise_for_status."""
    host = urlparse(url).netloc
    elapsed = time.monotonic() - _last_hit.get(host, 0.0)
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    hdrs = {"User-Agent": DEFAULT_UA, "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        hdrs.update(headers)
    try:
        resp = requests.get(url, timeout=timeout, headers=hdrs, **kw)
    finally:
        _last_hit[host] = time.monotonic()
    resp.raise_for_status()
    return resp


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def staleness_days(observation_iso: str) -> int:
    """Whole days between an observation date and now (UTC)."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(observation_iso, fmt).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
    else:
        return 0
    return max(0, (datetime.now(timezone.utc) - dt).days)


@dataclass
class NewsItem:
    ts: str
    source: str
    headline: str
    url: str
    classification: str
    matched_keywords: str


@dataclass
class CollectResult:
    signals: list[Signal] = field(default_factory=list)
    news: list[NewsItem] = field(default_factory=list)
    note: str | None = None          # short status, e.g. "manual-entry only"


class BaseCollector:
    name: str = "base"
    source: str = "base"
    fast: bool = False               # True = cheap enough for daily `collect --fast`

    def __init__(self, cfg: dict | None = None, secrets: dict | None = None,
                 conn=None):
        self.cfg = cfg or {}
        self.secrets = secrets or {}
        self.conn = conn      # optional; set by collect_all for collectors that need history

    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True))

    def collect(self) -> CollectResult:  # pragma: no cover - overridden
        raise NotImplementedError

    def safe_run(self) -> CollectResult:
        try:
            return self.collect()
        except Exception as exc:  # noqa: BLE001 - graceful degradation is the point
            log.warning("collector %s failed: %s", self.name, exc)
            return CollectResult(note=f"failed: {exc}")
