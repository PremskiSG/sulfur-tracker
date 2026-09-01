"""`tracker backfill` - seed the known 2026 baseline datapoints so the dashboard and
z-scores are not empty on first run. Idempotent: a second backfill is a no-op unless
force=True (append-only DB, so we guard on an existing backfill run).

Figures are the ones given in the project brief. A few metrics get 2-3 points so the
trailing-baseline std is non-zero and the first composite is meaningful rather than 0.
"""
from __future__ import annotations

from sulfur_tracker import db
from sulfur_tracker.collectors.base import staleness_days
from sulfur_tracker.signal import Confidence, Signal

# (metric, source, value, unit, observation_date)
SEED_ROWS = [
    # China sulfur price (CNY/t) -- a short series to give variance for the z-score
    ("sulfur_price_cn", "seed", 8000.0, "CNY/t", "2026-06-20"),
    ("sulfur_price_cn", "seed", 9650.0, "CNY/t", "2026-06-30"),
    ("sulfur_price_cn", "seed", 8569.0, "CNY/t", "2026-07-08"),
    # Indonesia sulfur imports: NO fabricated monthly seeds — the real per-month values
    # come from Comtrade (`tracker history`). Better an incomplete chart than a fake flat
    # line (we only know the Q1'26 quarter total of 966 kt, not the monthly split).
    # Mideast official FOB prices (USD/t)
    ("ksp_fob", "seed", 805.0, "USD/t", "2026-06-15"),
    ("ksp_fob", "seed", 950.0, "USD/t", "2026-07-15"),
    ("adnoc_osp_fob", "seed", 1000.0, "USD/t", "2026-07-15"),
    # China sulfur port stocks — SMM Sulfuric Acid Weekly Review, Jul 10 2026: national
    # port inventory ~710,000 mt (= 710 kt), "at a decade low".
    ("china_port_stocks_kt", "seed", 710.0, "kt", "2026-07-10"),
    # China port stocks (SunSirs/SMM): decade lows, -68.8% YoY
    ("china_port_stocks_kt", "seed", 748.8, "kt", "2026-06-23"),
    ("china_port_stocks_kt", "seed", 727.9, "kt", "2026-07-03"),
    # Indonesian MHP output (kt nickel contained) — measured curtailment
    ("indonesia_mhp_output_kt_ni", "seed", 42.0, "kt Ni", "2026-01-31"),
    ("indonesia_mhp_output_kt_ni", "seed", 29.9, "kt Ni", "2026-06-30"),
    # Sulfur physically transiting Hormuz: 80 kt over the 3.5-month conflict vs ~640 kt
    # in the fortnight after the 17 Jun truce.
    ("hormuz_sulfur_transit_kt", "seed", 80.0, "kt", "2026-06-15"),
    ("hormuz_sulfur_transit_kt", "seed", 640.0, "kt", "2026-06-30"),
    # Landed (CIF/CFR) Indonesia prices; peaks are midpoints of the quoted ranges
    ("sulfur_cif_indonesia", "seed", 563.0, "USD/t", "2026-01-05"),
    ("sulfur_cif_indonesia", "seed", 1275.0, "USD/t", "2026-06-10"),
    ("acid_cfr_indonesia", "seed", 150.0, "USD/t", "2026-01-05"),
    ("acid_cfr_indonesia", "seed", 427.0, "USD/t", "2026-06-26"),
    # Demand destruction in phosphate
    ("map_utilisation_pct", "seed", 40.0, "%", "2026-06-30"),
    ("dap_utilisation_pct", "seed", 30.0, "%", "2026-06-30"),
    ("sulfur_cost_share_pct", "seed", 32.5, "%", "2026-01-05"),
    ("sulfur_cost_share_pct", "seed", 130.0, "%", "2026-06-30"),
    # Tampa sulfur contract ($/long ton CFR) — the two confirmed quarterly settlements
    # (no interpolation, so the chart stays honestly sparse):
    #   Q1 2026 $495/lt, Q2 2026 $655/lt (reported as of Jun 30, 2026).
    ("tampa_sulfur_cfr", "seed", 495.0, "USD/lt", "2026-03-31"),
    ("tampa_sulfur_cfr", "seed", 655.0, "USD/lt", "2026-06-30"),
]


def already_seeded(conn) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) c FROM runs WHERE kind='backfill'").fetchone()
    return int(row["c"]) > 0


def backfill(conn, force: bool = False) -> int:
    if already_seeded(conn) and not force:
        return 0
    run_id = db.start_run(conn, kind="backfill")
    n = 0
    for metric, source, value, unit, obs_date in SEED_ROWS:
        sig = Signal(source=source, metric=metric, value=value, unit=unit,
                     timestamp=obs_date, confidence=Confidence.MANUAL.value,
                     staleness_days=staleness_days(obs_date))
        db.insert_signal(conn, run_id, sig)
        n += 1
    # implied HPAL sulfur demand = MHP nickel output x sulfur intensity
    from sulfur_tracker.config import load_config
    intensity = float(load_config().get("sulfur_per_nickel_t", 11.0))
    for metric, source, value, unit, obs_date in SEED_ROWS:
        if metric != "indonesia_mhp_output_kt_ni":
            continue
        sig = Signal(source=source, metric="implied_sulfur_demand_kt",
                     value=round(value * intensity, 1), unit="kt(mo)",
                     timestamp=obs_date, confidence=Confidence.MANUAL.value,
                     staleness_days=staleness_days(obs_date))
        db.insert_signal(conn, run_id, sig)
        n += 1
    db.finish_run(conn, run_id)
    return n
