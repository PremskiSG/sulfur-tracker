"""Composite scoring: per-metric z-score vs trailing baseline, direction-normalized
so positive = tightening, tier-weighted into a -100..+100 gauge with labeled zones.

Also runs the Indonesia contamination check: falling imports with no curtailment news
means the market is drawing down inventory and curtailments are still weeks out.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from sulfur_tracker import db
from sulfur_tracker.config import scoring_config
from sulfur_tracker.signal import GROUPS, SIGNAL_SPEC, Direction, MetricSpec

# Defaults; overridable via config.yaml -> scoring:
DEFAULTS = {
    "baseline_days": 90,
    "min_points_for_z": 2,     # need >=2 points and non-zero spread for a real z
    "z_clip": 3.0,             # clip weighted mean z to +/- this before scaling
    "zones": {                 # composite thresholds (tightening is positive)
        "acute": 60,
        "tightening": 20,
        "easing": -20,         # <= easing; between easing and tightening = stable
        "acute_easing": -60,
    },
    "contamination": {
        "news_window_days": 21,
        "curtailment_keywords": ["curtailment", "care and maintenance",
                                 "suspend", "output cut", "force majeure"],
    },
}


@dataclass
class SignalScore:
    metric: str
    label: str
    group: str
    weight: float
    value: float | None
    unit: str
    z: float                    # direction-normalized (positive = tightening)
    contribution: float         # weight * z (pre-normalization numerator term)
    points: int                 # history points used
    staleness_days: int
    stale: bool
    confidence: str
    direction: str
    available: bool


@dataclass
class GroupScore:
    group: str
    label: str
    contribution: float      # this group's points on the -100..+100 scale
    weight: float            # available weight in the group
    signals: int             # available signals in the group


@dataclass
class ScoreResult:
    composite: float
    zone: str
    coverage_pct: float
    max_staleness_days: int
    signals: list[SignalScore] = field(default_factory=list)
    contamination_flag: str | None = None
    groups: list[GroupScore] = field(default_factory=list)

    @property
    def available_signals(self) -> list[SignalScore]:
        return [s for s in self.signals if s.available]


def _cfg() -> dict:
    c = dict(DEFAULTS)
    user = scoring_config()
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(c.get(k), dict):
            merged = dict(c[k]); merged.update(v); c[k] = merged
        else:
            c[k] = v
    return c


def _zone(composite: float, zones: dict) -> str:
    if composite >= zones["acute"]:
        return "acute"
    if composite >= zones["tightening"]:
        return "tightening"
    if composite <= zones["acute_easing"]:
        return "acute-easing"
    if composite <= zones["easing"]:
        return "easing"
    return "stable"


def _score_metric(conn, spec: MetricSpec, cfg: dict) -> SignalScore:
    rows = db.history(conn, spec.metric, days=cfg["baseline_days"])
    latest = db.latest_signal(conn, spec.metric)
    if not rows or latest is None:
        return SignalScore(spec.metric, spec.label, spec.group, spec.weight, None,
                           spec.unit, 0.0, 0.0, 0, 0, False,
                           "n/a", Direction.NEUTRAL.value, available=False)

    values = [r["value"] for r in rows if r["value"] is not None]
    latest_val = latest["value"]
    staleness = latest["staleness_days"] or 0
    stale = staleness > spec.cadence_days
    z = 0.0
    if len(values) >= cfg["min_points_for_z"]:
        mean = statistics.fmean(values)
        try:
            sd = statistics.stdev(values)
        except statistics.StatisticsError:
            sd = 0.0
        if sd > 0:
            z = (latest_val - mean) / sd
    # direction-normalize so positive = tightening
    z_norm = spec.sign * z
    if z_norm > 0.15:
        direction = Direction.TIGHTENING.value
    elif z_norm < -0.15:
        direction = Direction.EASING.value
    else:
        direction = Direction.NEUTRAL.value

    return SignalScore(
        metric=spec.metric, label=spec.label, group=spec.group, weight=spec.weight,
        value=latest_val, unit=spec.unit, z=z_norm, contribution=spec.weight * z_norm,
        points=len(values), staleness_days=staleness, stale=stale,
        confidence=latest["confidence"] or "n/a", direction=direction, available=True,
    )


def _contamination_check(conn, signals: list[SignalScore], cfg: dict) -> str | None:
    imports = next((s for s in signals if s.metric == "indonesia_sulfur_imports_kt"), None)
    if imports is None or not imports.available:
        return None
    # imports "falling" = tightening direction (higher_means=easing, so a drop
    # normalizes to positive/tightening z)
    imports_falling = imports.z > 0.15
    if not imports_falling:
        return None
    cc = cfg["contamination"]
    hits = 0
    for kw in cc["curtailment_keywords"]:
        hits += db.news_with_keyword(conn, kw, cc["news_window_days"])
    if hits == 0:
        return ("Inventory drawdown phase: Indonesia sulfur imports are falling but no "
                "curtailment news in the last %d days -- curtailments expected in "
                "30-60 days." % cc["news_window_days"])
    return None


def score(conn) -> ScoreResult:
    cfg = _cfg()
    signals = [_score_metric(conn, spec, cfg) for spec in SIGNAL_SPEC.values()]

    avail = [s for s in signals if s.available]
    total_weight = sum(SIGNAL_SPEC[m].weight for m in SIGNAL_SPEC)
    avail_weight = sum(s.weight for s in avail)
    coverage = 100.0 * avail_weight / total_weight if total_weight else 0.0

    if avail_weight > 0:
        weighted_mean_z = sum(s.contribution for s in avail) / avail_weight
    else:
        weighted_mean_z = 0.0
    clip = cfg["z_clip"]
    clamped = max(-clip, min(clip, weighted_mean_z))
    composite = round(100.0 * clamped / clip, 1)

    zone = _zone(composite, cfg["zones"])
    max_stale = max((s.staleness_days for s in avail), default=0)
    contamination = _contamination_check(conn, signals, cfg)

    # Decompose the (pre-clip) composite into per-group contributions, so the score reads
    # as "tightening is coming from X". Group contributions sum to the unclamped composite.
    groups: list[GroupScore] = []
    scale = (100.0 / clip / avail_weight) if avail_weight > 0 else 0.0
    for gkey, (_order, label, _base) in sorted(GROUPS.items(), key=lambda kv: kv[1][0]):
        gsigs = [s for s in avail if s.group == gkey]
        groups.append(GroupScore(
            group=gkey, label=label,
            contribution=round(sum(s.contribution for s in gsigs) * scale, 1),
            weight=round(sum(s.weight for s in gsigs), 2), signals=len(gsigs)))

    return ScoreResult(
        composite=composite, zone=zone, coverage_pct=round(coverage, 1),
        max_staleness_days=max_stale, signals=signals,
        contamination_flag=contamination, groups=groups,
    )
