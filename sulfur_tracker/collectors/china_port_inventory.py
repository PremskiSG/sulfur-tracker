"""Tier 1 - Chinese sulfur port stocks (kt). The best free proxy, but SMM/Longzhong
headline figures sit behind a login, so the default path is manual entry:
    tracker input china_ports <kt>
An optional best-effort metal.com scrape can be enabled in config, but it is JS-heavy
and unreliable, so it is off by default. Higher stocks = easing.
"""
from __future__ import annotations

from sulfur_tracker.collectors.base import BaseCollector, CollectResult

METAL_COM_URL = "https://www.metal.com/en/sulphur"


class ChinaPortInventory(BaseCollector):
    name = "china_port_inventory"
    source = "manual"
    fast = False

    def collect(self) -> CollectResult:
        if self.cfg.get("scrape_metal_com", False):
            # Best-effort only; metal.com renders values client-side, so this rarely
            # yields a figure. Left as an explicit opt-in hook.
            raise NotImplementedError("metal.com scrape not reliable; use manual entry")
        return CollectResult(note="manual-entry only: tracker input china_ports <kt>")
