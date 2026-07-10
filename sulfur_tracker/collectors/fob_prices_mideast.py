"""Tier 2 - Mideast official sulfur prices: Kuwait KSP and Adnoc OSP (monthly, fob).
Announced publicly and reported in trade press but not on a clean free endpoint, so
the default path is manual entry:
    tracker input ksp <usd_per_t>
    tracker input adnoc_osp <usd_per_t>
Higher official prices = tightening.
"""
from __future__ import annotations

from sulfur_tracker.collectors.base import BaseCollector, CollectResult


class FobPricesMideast(BaseCollector):
    name = "fob_prices_mideast"
    source = "manual"
    fast = False

    def collect(self) -> CollectResult:
        return CollectResult(
            note="manual-entry: tracker input ksp <usd/t> | tracker input adnoc_osp <usd/t>")
