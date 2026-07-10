"""Collector registry + collect_all orchestration with graceful degradation."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sulfur_tracker import db
from sulfur_tracker.collectors.ais_gulf_transits import AisGulfTransits
from sulfur_tracker.collectors.base import BaseCollector
from sulfur_tracker.collectors.china_port_inventory import ChinaPortInventory
from sulfur_tracker.collectors.fob_prices_mideast import FobPricesMideast
from sulfur_tracker.collectors.fred_acid import FredAcid
from sulfur_tracker.collectors.indonesia_imports import IndonesiaImports
from sulfur_tracker.collectors.llm_price_scan import LlmPriceScan
from sulfur_tracker.collectors.news_monitor import NewsMonitor
from sulfur_tracker.collectors.sulfur_price_cn import SulfurPriceCN

log = logging.getLogger("sulfur_tracker.collectors")

COLLECTORS: list[type[BaseCollector]] = [
    # Gulf supply
    AisGulfTransits, FobPricesMideast,
    LlmPriceScan,  # opt-in (needs DeepSeek key): fills KSP/Adnoc from news via LLM
    # Landed balance
    SulfurPriceCN, IndonesiaImports, ChinaPortInventory,
    # Background / reference (not scored)
    NewsMonitor,   # only feeds the contamination check
    FredAcid,      # US sulfuric-acid PPI (free FRED history)
]

# Aliases for `tracker input <alias> <value>` -> (metric, unit, source).
MANUAL_INPUTS: dict[str, tuple[str, str, str]] = {
    "china_ports": ("china_port_stocks_kt", "kt", "manual"),
    "ais": ("gulf_sulfur_transits_wk", "vessels/wk", "manual"),
    "ksp": ("ksp_fob", "USD/t", "manual"),
    "adnoc_osp": ("adnoc_osp_fob", "USD/t", "manual"),
    "tampa_sulfur": ("tampa_sulfur_cfr", "USD/lt", "manual"),
    # For keying in historical China spot prices from SunSirs/TradingEconomics, e.g.
    #   tracker input sulfur_price 3860 --date 2025-11-14
    "sulfur_price": ("sulfur_price_cn", "CNY/t", "manual"),
}


@dataclass
class CollectorOutcome:
    name: str
    signals: int
    news: int
    note: str | None


def collect_all(conn, run_id, cfg: dict, secrets: dict,
                fast: bool = False) -> list[CollectorOutcome]:
    outcomes: list[CollectorOutcome] = []
    collectors_cfg = (cfg or {}).get("collectors", {})
    for cls in COLLECTORS:
        ccfg = collectors_cfg.get(cls.name, {}) or {}
        if not ccfg.get("enabled", True):
            continue
        if fast and not cls.fast:
            continue
        inst = cls(ccfg, secrets, conn=conn)
        result = inst.safe_run()
        for sig in result.signals:
            db.insert_signal(conn, run_id, sig)
        news_written = 0
        for n in result.news:
            if db.insert_news(conn, run_id, n.ts, n.source, n.headline, n.url,
                              n.classification, n.matched_keywords):
                news_written += 1
        outcomes.append(CollectorOutcome(cls.name, len(result.signals),
                                         news_written, result.note))
        log.info("collector %s: %d signals, %d news %s", cls.name,
                 len(result.signals), news_written,
                 f"({result.note})" if result.note else "")
    return outcomes
