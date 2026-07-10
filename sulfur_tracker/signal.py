"""The normalized Signal every collector returns, plus the SIGNAL_SPEC registry that
declares each metric's functional group, composite weight, direction semantics, unit and
cadence.

Signals are organized by their **function in the causal chain** (Gulf supply -> landed
balance -> downstream demand), not by a flat confidence tier, so the composite can be
decomposed into "is tightening coming from supply or from demand?". Each signal's weight
is explicit: weight = group_base x reliability_factor, so perpetually-empty manual signals
don't sit at high nominal weight.

Direction convention for the composite: positive contribution = TIGHTENING. Each metric
declares `higher_means` so scoring can flip raw z-scores accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Direction(str, Enum):
    TIGHTENING = "tightening"
    EASING = "easing"
    NEUTRAL = "neutral"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MANUAL = "manual"


# Functional groups (display order = upstream -> downstream along the chain) and their
# base weights. Landed balance is the core, so it carries the highest base.
GROUPS: dict[str, tuple[int, str, float]] = {
    "gulf_supply":    (1, "Gulf supply", 2.5),
    "landed_balance": (2, "Landed sulfur balance", 3.0),
}

# Reliability multipliers applied to the group base to get a signal's weight.
RELIABILITY: dict[str, float] = {"live": 1.0, "semi": 0.8, "manual": 0.5}


@dataclass
class Signal:
    """One observation from one source, normalized."""

    source: str
    metric: str
    value: float
    unit: str
    timestamp: str  # ISO-8601 observation time
    direction_vs_baseline: str = Direction.NEUTRAL.value
    confidence: str = Confidence.MEDIUM.value
    staleness_days: int = 0


@dataclass(frozen=True)
class MetricSpec:
    metric: str
    source: str          # collector name that produces it
    group: str           # key into GROUPS
    weight: float        # explicit composite weight (group_base x reliability, tunable)
    reliability: str     # live | semi | manual
    higher_means: str    # Direction.TIGHTENING or Direction.EASING value
    unit: str
    cadence_days: int    # expected refresh interval; drives staleness flagging
    label: str

    @property
    def group_label(self) -> str:
        return GROUPS[self.group][1]

    @property
    def group_order(self) -> int:
        return GROUPS[self.group][0]

    @property
    def sign(self) -> float:
        """+1 if a higher raw value means tightening, -1 if it means easing."""
        return 1.0 if self.higher_means == Direction.TIGHTENING.value else -1.0


def _spec(metric, source, group, weight, reliability, higher_means, unit,
          cadence_days, label):
    return MetricSpec(metric, source, group, weight, reliability, higher_means.value,
                      unit, cadence_days, label)


# The scored universe. Anything a collector emits that is NOT listed here is stored as a
# reference signal but excluded from the composite (e.g. raw nickel_price, fred_acid_ppi).
SIGNAL_SPEC: dict[str, MetricSpec] = {
    s.metric: s
    for s in [
        # --- Gulf supply (upstream, most leading) ---
        _spec("gulf_sulfur_transits_wk", "ais_gulf_transits", "gulf_supply", 1.25,
              "manual", Direction.EASING, "vessels/wk", 7, "Gulf sulfur laden departures"),
        _spec("ksp_fob", "fob_prices_mideast", "gulf_supply", 1.0,
              "semi", Direction.TIGHTENING, "USD/t", 35, "Kuwait KSP FOB"),
        _spec("adnoc_osp_fob", "fob_prices_mideast", "gulf_supply", 1.0,
              "semi", Direction.TIGHTENING, "USD/t", 35, "Adnoc OSP FOB"),
        # --- Landed sulfur balance (midstream, the core) ---
        _spec("sulfur_price_cn", "sulfur_price_cn", "landed_balance", 3.0,
              "live", Direction.TIGHTENING, "CNY/t", 3, "China sulfur spot price"),
        _spec("indonesia_sulfur_imports_kt", "indonesia_imports", "landed_balance", 2.7,
              "live", Direction.EASING, "kt(mo)", 45, "Indonesia sulfur imports (monthly)"),
        _spec("china_port_stocks_kt", "china_port_inventory", "landed_balance", 1.5,
              "manual", Direction.EASING, "kt", 7, "China sulfur port stocks"),
        # Manual reliability: the $/lt value isn't reliably in free news headlines (they
        # say "settled at a record" without the number), so the LLM-scan is best-effort
        # and the real path is quarterly manual entry (`tracker input tampa_sulfur`).
        _spec("tampa_sulfur_cfr", "llm_price_scan", "landed_balance", 1.5,
              "manual", Direction.TIGHTENING, "USD/lt", 100, "Tampa sulfur contract (CFR)"),
        # (Downstream demand group dropped — no nickel-based signals per user.)
    ]
}


def spec_for(metric: str) -> MetricSpec | None:
    return SIGNAL_SPEC.get(metric)


# Tracked prices shown/charted on the dashboard but NOT scored into the composite.
REFERENCE_METRICS: dict[str, tuple[str, str]] = {
    "fred_acid_ppi": ("US sulfuric-acid price index (FRED)", "index"),
}


# Per-signal documentation shown on the dashboard: metric -> (what it tracks, why it
# matters). Direction semantics come from each MetricSpec.higher_means.
SIGNAL_DOC: dict[str, tuple[str, str]] = {
    "china_port_stocks_kt": (
        "How much sulfur is sitting in storage at China's ports.",
        "Think of these ports as China's **pantry** for sulfur. Every fertilizer and "
        "battery-chemical factory eats from this pantry. If it's full, nobody panics when "
        "a delivery is late. But if the shelves are emptying *and* ships from the Gulf "
        "aren't showing up, factories start to worry — and that worry becomes panic-buying "
        "and price spikes weeks before anyone officially runs out. Watching the pantry "
        "level is the earliest honest read on whether there's really enough to go around."),
    "sulfur_price_cn": (
        "The day-to-day market price of sulfur in China, the world's biggest buyer.",
        "Normally when something gets pricey, sellers make more and the price calms down. "
        "Sulfur **can't do that** — it's a leftover from refining oil and gas, so nobody "
        "can conjure up extra just because prices are high. That makes the price almost a "
        "pure **fear-and-scarcity gauge**: when Gulf ships are stuck and the pantry is "
        "draining, buyers scramble and bid it up fast (it's up ~277% in a year). It's the "
        "fastest signal we have — it reacts in days, not weeks."),
    "gulf_sulfur_transits_wk": (
        "How many loaded sulfur ships leave the big Gulf ports each week.",
        "This is like standing at the highway on-ramp and **counting trucks leaving the "
        "warehouse**, instead of waiting to see empty shelves at the store. Almost all the "
        "sulfur starts at a handful of Gulf ports (Ruwais, Ras Laffan, Jubail, Shuaiba). "
        "If fewer loaded ships sail, we know a shortage is coming a month or two before it "
        "shows up anywhere else. It's the earliest warning bell in the whole chain."),
    "indonesia_sulfur_imports_kt": (
        "How much sulfur Indonesia imports each month.",
        "Indonesia's nickel plants are **first in line to go hungry** when Gulf sulfur is "
        "cut off — they buy ~90% of their sulfur from the Gulf to make battery ingredients. "
        "So Indonesia's monthly imports are the **canary in the coal mine**: when they "
        "drop, it's hard proof the Gulf supply really isn't arriving — not just a rumor. "
        "This is our most reliable real-data signal and the trigger for the shortage-timing "
        "alarm (see the contamination check)."),
    "tampa_sulfur_cfr": (
        "The US benchmark sulfur price — molten sulfur delivered to Tampa, Florida ($/long ton).",
        "This is the **US version of the China price**: what sulfur costs on the other side "
        "of the world, feeding the American phosphate-fertilizer belt. If Tampa is spiking "
        "too (it's up ~600% since 2024), the squeeze is **global, not just an Asia story** — "
        "a strong, independent second geography confirming the disruption is real."),
    "ksp_fob": (
        "Kuwait's official 'this is what sulfur costs now' price, posted monthly.",
        "Each month the big Gulf sellers publish an official price. When Kuwait **raises** "
        "it, that's the seller itself admitting supply is tight and rationing by price — "
        "like a shop putting up a **'limit 2 per customer'** sign. It confirms the squeeze "
        "is deliberate and durable, not a one-day blip."),
    "adnoc_osp_fob": (
        "The UAE's (Adnoc's) official monthly sulfur price.",
        "Same idea as Kuwait's price, from a **different** big Gulf seller. One seller "
        "raising prices could be a fluke; **Kuwait and the UAE both** hiking at the same "
        "time is strong, independent proof the shortage is real and widespread."),
    "fred_acid_ppi": (
        "US government price index for sulfuric acid (FRED, monthly since 1987).",
        "Sulfuric acid is sulfur's **main product** — burn sulfur, get acid, which "
        "fertilizer and battery plants actually use. This free official index shows the "
        "**long-run US acid price trend**, so you can see how far above normal today's "
        "levels sit. Context, not scored."),
}
