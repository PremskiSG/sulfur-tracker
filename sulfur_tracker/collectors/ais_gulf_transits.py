"""Tier 1 - laden sulfur/bulk carrier departures from Gulf sulfur ports toward Asia,
counted as vessels/week (not tonnage). Requires an AIS provider key; with no key it
degrades to manual entry:
    tracker input ais <vessels_per_week>

The port polygons and vessel-type filters are defined here so a provider adapter can be
dropped in later just by supplying credentials in secrets.yaml. Higher departures =
more supply in transit = easing.
"""
from __future__ import annotations

from sulfur_tracker.collectors.base import BaseCollector, CollectResult

# Approximate bounding boxes (lon/lat) for the main Gulf sulfur export terminals.
GULF_SULFUR_PORTS = {
    "ruwais":     {"lon": (52.55, 52.85), "lat": (24.05, 24.25)},   # UAE
    "ras_laffan": {"lon": (51.50, 51.75), "lat": (25.85, 26.05)},   # Qatar
    "jubail":     {"lon": (49.55, 49.80), "lat": (26.95, 27.15)},   # Saudi
    "shuaiba":    {"lon": (48.10, 48.30), "lat": (29.00, 29.15)},   # Kuwait
}
# AIS ship types: 70-79 = cargo (bulk carriers). Sulfur moves on dry-bulk tonnage.
VESSEL_TYPES = list(range(70, 80))
# Only count vessels heading east/south (toward Asia), not intra-Gulf hops.
MIN_DRAFT_M = 6.0  # laden filter; ballast departures ride higher


def _query_provider(secrets: dict) -> int | None:
    """Adapter stub for MarineTraffic / Datalastic / aisstream.io. Wired only when a
    key is present; otherwise returns None so the collector degrades to manual."""
    key = secrets.get("ais_api_key")
    if not key:
        return None
    # Real implementation would poll the provider for each polygon in
    # GULF_SULFUR_PORTS, filter by VESSEL_TYPES + MIN_DRAFT_M + eastbound course, and
    # count distinct laden departures in the trailing 7 days.
    raise NotImplementedError("AIS provider adapter not implemented for this key")


class AisGulfTransits(BaseCollector):
    name = "ais_gulf_transits"
    source = "manual"
    fast = False

    def collect(self) -> CollectResult:
        count = _query_provider(self.secrets)
        if count is None:
            return CollectResult(
                note="manual-entry (no AIS key): tracker input ais <vessels/wk>")
        from sulfur_tracker.collectors.base import now_iso, Signal
        from sulfur_tracker.signal import Confidence, Direction
        sig = Signal("ais", "gulf_sulfur_transits_wk", float(count), "vessels/wk",
                     now_iso()[:10], Direction.NEUTRAL.value, Confidence.MEDIUM.value, 0)
        return CollectResult(signals=[sig])
