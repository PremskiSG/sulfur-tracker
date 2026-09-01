"""The export-restriction register: supply removed by government policy rather than by
the strait. Kazakhstan, Russia and Turkey all banned sulfur exports during 2026, which
explains more of the price action than any single trade flow.

Because each measure has a known start date, the share of world supply under restriction
is computable *retroactively* — so the scored signal ships with real history instead of
starting empty.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date

from sulfur_tracker import db
from sulfur_tracker.collectors.base import staleness_days
from sulfur_tracker.signal import Confidence, Direction, Signal

log = logging.getLogger("sulfur_tracker.restrictions")

# World sulfur production, kt/yr (USGS: ~84 Mt in 2025). The denominator for "what share
# of global supply is under an export restriction".
GLOBAL_SULFUR_KT_YR = 84_000.0

# (country_code, measure, commodity, start, end, annual_kt, source, note)
KNOWN_RESTRICTIONS = [
    (398, "export_ban", "sulfur", "2026-06-27", None, 4600.0, "SunSirs / KZ MoE",
     "Order No. 1363: total suspension of sulfur exports. Exported 4.6 Mt in 2025; "
     "OCP Morocco sourced ~2.5 Mt/yr (44% of its imports) from Kazakhstan."),
    (643, "export_ban", "sulfur", "2026-01-01", "2026-12-31", 2500.0, "SunSirs",
     "Russian export ban extended to 31 Dec 2026. Gazprom Astrakhan (4.8 Mt capacity) "
     "running one line; Orenburg (1.55 Mt) damaged 24 Jun."),
    (792, "export_ban", "sulfur", "2026-04-07", "2026-09-30", 700.0, "SunSirs",
     "Turkish export ban from 7 Apr through Q3 2026."),
    (156, "acid_export_ban", "acid", "2026-05-01", "2026-12-31", 4650.0, "SMM / SunSirs",
     "China halted sulfuric-acid exports to protect domestic phosphate. Acid, not "
     "sulfur — excluded from the sulfur supply maths."),
]


def seed_restrictions(conn) -> int:
    for cc, measure, commodity, start, end, kt, source, note in KNOWN_RESTRICTIONS:
        db.upsert_restriction(conn, cc, measure, start, end_date=end, annual_kt=kt,
                              commodity=commodity, source=source, note=note)
    conn.commit()
    return len(KNOWN_RESTRICTIONS)


def _month_ends(first: date, last: date) -> list[date]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(date(y, m, calendar.monthrange(y, m)[1]))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def restriction_series(conn, through: date | None = None) -> int:
    """Emit `supply_under_restriction_pct` at each month-end from the first ban start to
    now. Replaces any prior computed series (source='computed') so it is re-runnable."""
    rows = db.restrictions(conn, commodity="sulfur")
    if not rows:
        return 0
    through = through or date.today()
    first = min(date.fromisoformat(r["start_date"]) for r in rows)
    conn.execute("DELETE FROM signals WHERE metric='supply_under_restriction_pct' "
                 "AND source='computed'")
    conn.commit()
    run_id = db.start_run(conn, "backfill")
    n = 0
    for me in _month_ends(first, through):
        iso = me.isoformat()
        pct = round(100.0 * db.restricted_kt_on(conn, iso) / GLOBAL_SULFUR_KT_YR, 2)
        db.insert_signal(conn, run_id, Signal(
            "computed", "supply_under_restriction_pct", pct, "%", iso,
            Direction.NEUTRAL.value, Confidence.MEDIUM.value, staleness_days(iso)))
        n += 1
    db.finish_run(conn, run_id)
    return n


def refresh(conn, through: date | None = None) -> tuple[int, int]:
    """Seed the register and recompute the % series. Returns (measures, points)."""
    return seed_restrictions(conn), restriction_series(conn, through)
