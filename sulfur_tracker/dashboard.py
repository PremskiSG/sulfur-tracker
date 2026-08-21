"""Streamlit dashboard. Reads SQLite live on each load, so it always reflects the
latest `tracker run`. Launch with `tracker dashboard` or `streamlit run dashboard.py`.

The focus is tracking each signal's price with its historical trend. The composite is
shown as a slim one-line readout at the top (no gauge), and there is no news feed.
"""
from __future__ import annotations

import os
import sys

# Make the `sulfur_tracker` package importable when run as a bare script (e.g. Streamlit
# Cloud does `streamlit run sulfur_tracker/dashboard.py` without pip-installing the pkg):
# add the repo root (parent of this package dir) to sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from sulfur_tracker import countries, db
from sulfur_tracker.scoring import score
from sulfur_tracker.signal import GROUPS, REFERENCE_METRICS, SIGNAL_DOC, SIGNAL_SPEC

ZONE_LABEL = {
    "acute": "ACUTE TIGHTENING", "tightening": "TIGHTENING", "stable": "STABLE",
    "easing": "EASING", "acute-easing": "ACUTE EASING",
}
ZONE_COLOR = {
    "acute": "#b00020", "tightening": "#e8710a", "stable": "#5f6368",
    "easing": "#1a73e8", "acute-easing": "#174ea6",
}
DIR_COLOR = {"tightening": "#e8710a", "easing": "#1a73e8", "neutral": "#9aa0a6"}

# Manual-entry signals: no free historical series exists (SMM/AIS/trade-press are
# paywalled), so history is built up by entering values over time.
MANUAL_METRICS = {"china_port_stocks_kt", "gulf_sulfur_transits_wk", "ksp_fob",
                  "adnoc_osp_fob", "tampa_sulfur_cfr"}


def _break_gaps(df, gap_factor: float = 3.0):
    """Insert a NaN row wherever the series skips a reporting period, so plotly breaks
    the line instead of drawing a straight edge across missing months — a gap must look
    like a gap, not like a smooth trend (e.g. China has no 2025 data at all)."""
    if len(df) < 3:
        return df
    dates = pd.to_datetime(df["date"])
    deltas = dates.diff().dt.days.dropna()
    if deltas.empty:
        return df
    threshold = max(deltas.median() * gap_factor, 45)
    rows = []
    for i, (d, v) in enumerate(zip(df["date"], df["v"])):
        if i and (dates.iloc[i] - dates.iloc[i - 1]).days > threshold:
            mid = dates.iloc[i - 1] + (dates.iloc[i] - dates.iloc[i - 1]) / 2
            rows.append({"date": mid.strftime("%Y-%m-%d"), "v": float("nan")})
        rows.append({"date": d, "v": v})
    return pd.DataFrame(rows)


def trend_chart(conn, metric: str, unit: str) -> go.Figure | None:
    rows = db.history(conn, metric)
    if not rows or len(rows) < 2:
        return None
    df = pd.DataFrame([(r["ts"][:10], r["value"]) for r in rows], columns=["date", "v"])
    df = df.groupby("date", as_index=False)["v"].mean().sort_values("date")
    df = _break_gaps(df)
    fig = go.Figure(go.Scatter(
        x=df["date"], y=df["v"], mode="lines+markers", connectgaps=False,
        line=dict(width=2, color="#4c8bf5"), marker=dict(size=4),
        hovertemplate="%{x}<br>%{y:.1f} " + unit + "<extra></extra>"))
    fig.update_layout(height=170, margin=dict(t=8, b=24, l=8, r=8),
                      xaxis=dict(showgrid=False),
                      yaxis=dict(title=unit, gridcolor="rgba(128,128,128,0.15)"),
                      showlegend=False, plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


@st.cache_data(ttl=3600)
def cny_per_usd() -> float:
    """USDCNY (CNY per 1 USD) for showing USD equivalents. Live from yfinance, cached
    hourly, with a config fallback so the dashboard never breaks offline."""
    try:
        import yfinance as yf
        rate = float(yf.Ticker("CNY=X").fast_info["last_price"])
        if rate > 0:
            return rate
    except Exception:  # noqa: BLE001
        pass
    from sulfur_tracker.config import load_config
    return float(load_config().get("fx", {}).get("usd_cny", 7.15))


LONG_TON_KG = 1016.047  # 1 long ton = 2,240 lb ≈ 1.016 metric tonnes


def _equiv_suffix(value, unit) -> str:
    """A parenthetical equivalent in a comparable unit: CNY prices -> USD, and the Tampa
    long-ton price -> metric tonne (so it lines up with the USD/t Gulf prices)."""
    if value is None:
        return ""
    if "CNY" in unit:
        usd = value / cny_per_usd()
        tail = unit.split("/", 1)[1] if "/" in unit else "t"
        return f" (${usd:,.0f}/{tail})"
    if unit == "USD/lt":  # long ton -> metric tonne
        return f" (${value / (LONG_TON_KG / 1000):,.0f}/t)"
    return ""


def _signal_row(conn, label, value, unit, sub_html: str, metric):
    tracks, why = SIGNAL_DOC.get(metric, ("", ""))
    left, right = st.columns([2, 3])
    with left:
        st.markdown(f"**{label}**")
        if tracks:
            st.markdown(f"<div style='color:var(--text-color);opacity:0.75;"
                        f"font-size:0.9rem;margin:-4px 0 6px'>{tracks}</div>",
                        unsafe_allow_html=True)
        if value is None:
            st.caption("no data yet")
        else:
            st.markdown(f"<span style='font-size:1.9rem;font-weight:600'>{value:g}</span> "
                        f"<span style='color:#9aa0a6'>{unit}{_equiv_suffix(value, unit)}</span>",
                        unsafe_allow_html=True)
            yoy = db.latest_signal(conn, f"{metric}_yoy_pct")
            if yoy and yoy["value"] is not None:
                st.markdown(f"<div style='color:#e8710a;font-size:0.95rem;"
                            f"font-weight:500'>{yoy['value']:+.0f}% vs a year ago</div>",
                            unsafe_allow_html=True)
            if sub_html:
                st.markdown(f"<div style='color:#9aa0a6;font-size:0.85rem'>{sub_html}</div>",
                            unsafe_allow_html=True)
        if why:
            with st.expander("why it matters"):
                st.markdown(why)
    with right:
        fig = trend_chart(conn, metric, unit)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, key=f"c_{metric}")
        elif value is not None:
            if metric in MANUAL_METRICS:
                st.caption("manual entry — no free historical source; "
                           "enter values over time to build the trend")
            else:
                st.caption("history building — one datapoint so far")
    st.divider()


def main() -> None:
    st.set_page_config(page_title="Sulfur Tracker", layout="wide")
    st.title("Sulfur Tracker")
    st.caption("The 2026 Hormuz sulfur disruption, read from downstream signals — each "
               "tracked with its price and history, grouped by role in the chain.")

    conn = db.connect()
    result = score(conn)
    by_metric = {s.metric: s for s in result.signals}

    if result.contamination_flag:
        st.warning(result.contamination_flag)

    for gkey, (_order, glabel, _base) in sorted(GROUPS.items(), key=lambda kv: kv[1][0]):
        st.subheader(glabel)
        for metric, spec in SIGNAL_SPEC.items():
            if spec.group != gkey:
                continue
            s = by_metric.get(metric)
            sub_html = ""
            if s and s.available:
                dcol = DIR_COLOR.get(s.direction, "#9aa0a6")
                sub_html = (f"<span style='color:{dcol}'>{s.direction}</span> · "
                            f"z {s.z:+.2f} · "
                            f"stale {s.staleness_days}d{' ⚠' if s.stale else ''}")
            _signal_row(conn, spec.label, s.value if s else None, spec.unit,
                        sub_html, metric)

    st.subheader("Reference (not scored)")
    for metric, (label, unit) in REFERENCE_METRICS.items():
        latest = db.latest_signal(conn, metric)
        _signal_row(conn, label, latest["value"] if latest else None, unit, "", metric)

    _trade_flows_section(conn)


# Gulf columns always shown (in this order) for importers, so the table reads the same
# month to month even when a supplier drops to zero — that zero IS the signal.
GULF_ORDER = [784, 682, 414, 48, 512, 634, 364, 368]
MAX_NAMED_NON_GULF = 3     # importers: extra named columns beyond the Gulf/watch set
MAX_NAMED_EXPORT = 8       # exporters: top destinations to name
MIN_COLUMN_KT = 10.0       # a partner must ship this much (cumulative) to earn a column;
                           # below it they fold into Other rather than eating table width
# Strategically interesting origins that get a column whenever they clear MIN_COLUMN_KT,
# even if they miss the volume cut — Kazakhstan matters because any eastbound cargo is
# evidence of the rail diversion that only pencils at crisis prices.
WATCH_PARTNERS = [398]


def _flow_table(conn, reporter: int, flow: str):
    """Month x country table: months as rows, key partners as columns, plus Other,
    Total and (importers) Gulf %. Returns the DataFrame, or None if no data."""
    rows = db.flow_matrix(conn, reporter, flow)
    if not rows:
        return None

    by_month: dict[str, dict[int, float]] = {}
    totals: dict[int, float] = {}
    for r in rows:
        month = r["period"][:4] + "-" + r["period"][4:]
        by_month.setdefault(month, {})[r["partner_code"]] = r["kt"]
        totals[r["partner_code"]] = totals.get(r["partner_code"], 0.0) + (r["kt"] or 0)

    ranked = [c for c, _ in sorted(totals.items(), key=lambda kv: -kv[1])
              if totals[c] >= MIN_COLUMN_KT]
    if flow == "M":
        named = [c for c in GULF_ORDER if totals.get(c, 0) >= MIN_COLUMN_KT]
        named += [c for c in WATCH_PARTNERS
                  if totals.get(c, 0) >= MIN_COLUMN_KT and c not in named]
        named += [c for c in ranked if c not in named][:MAX_NAMED_NON_GULF]
    else:
        named = ranked[:MAX_NAMED_EXPORT]

    records = []
    for month in sorted(by_month):
        parts = by_month[month]
        row = {"Month": month}
        for code in named:
            row[countries.name(code)] = parts.get(code)
        other = sum(v for c, v in parts.items() if c not in named)
        row["Other"] = other or None
        total = sum(parts.values())
        row["Total"] = round(total, 1)
        if flow == "M":
            gulf = sum(v for c, v in parts.items() if c in countries.GULF)
            row["Gulf %"] = round(100 * gulf / total) if total else 0
        records.append(row)
    df = pd.DataFrame(records).set_index("Month")
    # float dtype so missing months render as blank cells, not the string "None"
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # drop partner columns that never shipped anything (all blank or all zero)
    keep = [c for c in df.columns
            if c in ("Other", "Total", "Gulf %") or df[c].fillna(0).abs().sum() > 0]
    return df[keep]


def _display_frame(df):
    """String-formatted copy for st.table: blanks for missing, 1dp for kt, % for share."""
    out = df.copy()
    for col in out.columns:
        if col == "Gulf %":
            out[col] = out[col].map(lambda v: "" if pd.isna(v) else f"{v:.0f}%")
        else:
            out[col] = out[col].map(lambda v: "" if pd.isna(v) else f"{v:,.1f}")
    return out


def _trade_flows_section(conn) -> None:
    st.divider()
    st.subheader("Trade flows (Comtrade)")
    st.caption("Who sells sulfur to whom, by month (HS 2503). Importer partner = origin; "
               "exporter partner = destination. Mirror-derived, monthly, ~2-month lag — a "
               "missing month is non-reporting, not zero. Browse-only, not scored.")
    tabs = st.tabs([c["name"] for c in countries.TRADE_COUNTRIES])
    for tab, c in zip(tabs, countries.TRADE_COUNTRIES):
        with tab:
            df = _flow_table(conn, c["reporter"], c["flow"])
            if df is None:
                st.caption("no data yet — run `tracker trade-flows`")
                continue
            latest = df.iloc[-1]
            cols = st.columns(3)
            cols[0].metric(f"{c['name']} {'imports' if c['flow'] == 'M' else 'exports'}",
                           f"{latest['Total']:.0f} kt",
                           help=f"latest month {df.index[-1]}")
            if c["flow"] == "M":
                cols[1].metric("Gulf share (latest)", f"{latest['Gulf %']:.0f}%")
            st.caption("kt per month by "
                       + ("origin" if c["flow"] == "M" else "destination")
                       + " — blank = no recorded shipments that month")
            # st.table renders the whole thing statically: every month visible at once,
            # no inner scrollbar (st.dataframe caps the height and virtualizes).
            st.table(_display_frame(df))


main()
