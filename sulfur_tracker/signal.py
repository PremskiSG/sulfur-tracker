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
    "supply_policy":  (0, "Supply policy (export bans)", 2.5),
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
    baseline_days: int | None = None   # override the global z-score window; slow policy
                                       # variables need a longer memory than 90 days

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
          cadence_days, label, baseline_days=None):
    return MetricSpec(metric, source, group, weight, reliability, higher_means.value,
                      unit, cadence_days, label, baseline_days)


# The scored universe. Anything a collector emits that is NOT listed here is stored as a
# reference signal but excluded from the composite (e.g. raw nickel_price, fred_acid_ppi).
SIGNAL_SPEC: dict[str, MetricSpec] = {
    s.metric: s
    for s in [
        # --- Supply policy (upstream of the strait: bans remove supply outright) ---
        _spec("supply_under_restriction_pct", "restrictions", "supply_policy", 1.25,
              "manual", Direction.TIGHTENING, "%", 30,
              "World supply under export ban", baseline_days=365),
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
    "indonesia_mhp_output_kt_ni": ("Indonesia MHP output (nickel contained)", "kt Ni"),
    "implied_sulfur_demand_kt": ("Implied HPAL sulfur demand", "kt(mo)"),
    "hormuz_sulfur_transit_kt": ("Sulfur transiting Hormuz", "kt"),
    "sulfur_cif_indonesia": ("Sulfur landed Indonesia (CIF)", "USD/t"),
    "acid_cfr_indonesia": ("Sulfuric acid landed Indonesia (CFR)", "USD/t"),
    "map_utilisation_pct": ("MAP fertilizer plant utilisation", "%"),
    "dap_utilisation_pct": ("DAP fertilizer plant utilisation", "%"),
    "sulfur_cost_share_pct": ("Sulfur as share of phosphate production cost", "%"),
    "china_sulfur_imports_kt": ("China sulfur imports (SMM / customs)", "kt(mo)"),
    "china_acid_exports_kt": ("China sulfuric-acid exports (SMM / customs)", "kt(mo)"),
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
    "supply_under_restriction_pct": (
        "The share of world sulfur supply sitting under a government export ban.",
        "Not all missing sulfur is stuck on a ship. In 2026 three producing countries "
        "simply **banned exports outright** — Kazakhstan (27 Jun, 4.6 Mt/yr), Russia "
        "(through Dec) and Turkey. That supply still exists; it just cannot legally "
        "leave. This is the **policy layer above the strait**, and it can keep the "
        "market tight long after Hormuz reopens — which is exactly what makes it worth "
        "scoring separately from shipping flows."),
    "indonesia_mhp_output_kt_ni": (
        "How much half-finished nickel (MHP) Indonesia actually produced, in nickel tonnes.",
        "This is **curtailment you can measure** instead of infer. HPAL plants burn "
        "10-12 tonnes of sulfur per tonne of nickel, so when output falls the sulfur is "
        "genuinely not being consumed. Output slid from **42.0 kt Ni in January to 29.9 "
        "kt in June** — the shortage biting in the real economy, not just in prices."),
    "implied_sulfur_demand_kt": (
        "MHP output converted into the sulfur it must have consumed.",
        "Multiply nickel output by ~11 t of sulfur per tonne and you get the sulfur that "
        "Indonesia's HPAL plants actually burned. It turns a nickel number into a "
        "**demand number**, directly comparable with the import volumes we track."),
    "hormuz_sulfur_transit_kt": (
        "Tonnes of sulfur physically passing through the Strait of Hormuz.",
        "The most direct measure of the blockage there is: **~80 kt moved during the "
        "whole 3.5-month conflict, versus ~640 kt in the fortnight after the truce**. "
        "Our vessel-counting signal never had a data source; this one does."),
    "sulfur_cif_indonesia": (
        "What a tonne of sulfur costs delivered to Indonesia, freight included.",
        "Gulf sellers quote **fob** — price at their own dock. Buyers pay **CIF**: fob "
        "plus freight, which blew out to $140-145/t. CIF went from **$563 to "
        "$1,250-1,300** at the peak, so it captures pain that the fob prices hide."),
    "acid_cfr_indonesia": (
        "What sulfuric acid costs delivered to Indonesia.",
        "When sulfur is unobtainable, HPAL plants buy finished **acid** instead — at a "
        "price that went from **$150 to $410-445/t**. Rising acid CFR alongside rising "
        "sulfur CIF means buyers are paying up on both routes at once."),
    "map_utilisation_pct": (
        "How hard MAP fertilizer plants are running, as a % of capacity.",
        "Fertilizer is the biggest sulfur consumer, so idle plants are the clearest sign "
        "of **demand destruction** — buyers priced out rather than supplied. MAP fell to "
        "~40% of capacity."),
    "dap_utilisation_pct": (
        "How hard DAP fertilizer plants are running, as a % of capacity.",
        "The companion to MAP, and it fell further — to **~30%**. Two-thirds of the "
        "capacity standing still is demand that has simply stopped buying sulfur."),
    "sulfur_cost_share_pct": (
        "Sulfur's share of the cost of making phosphate fertilizer.",
        "Normally sulfur is **30-35%** of production cost. In this crisis it passed "
        "**130%** — the raw material costs more than the finished product sells for. "
        "That single number explains why plants idled: not scarcity, but arithmetic."),
    "china_sulfur_imports_kt": (
        "How much sulfur China imports each month (Chinese customs, via SMM).",
        "China is the **world's biggest sulfur buyer**, so this is the single most "
        "important demand number there is — and UN Comtrade stopped carrying it after "
        "2024, which is why we read it from SMM's customs write-ups instead. It is "
        "collapsing: **−85% year-on-year in June 2026**. When the largest buyer simply "
        "cannot get cargoes, that is the shortage in its purest form."),
    "china_acid_exports_kt": (
        "How much sulfuric acid China ships abroad each month (customs, via SMM).",
        "Sulfuric acid is what sulfur gets **turned into** — and China makes over 40% of "
        "the world's supply, much of it as a free byproduct of its copper and zinc "
        "smelters. On 1 May 2026 China **banned acid exports** to protect its own "
        "fertilizer industry, and shipments fell off a cliff: **~980 tonnes in June, "
        "−99.7% year-on-year**. Note this is acid, not sulfur — it does not refill a "
        "sulfur shortage (you cannot turn acid back into sulfur), but shutting it off "
        "makes every acid buyer outside China scramble."),
    "fred_acid_ppi": (
        "US government price index for sulfuric acid (FRED, monthly since 1987).",
        "Sulfuric acid is sulfur's **main product** — burn sulfur, get acid, which "
        "fertilizer and battery plants actually use. This free official index shows the "
        "**long-run US acid price trend**, so you can see how far above normal today's "
        "levels sit. Context, not scored."),
}
