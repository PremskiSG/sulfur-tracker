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


def trend_chart(conn, metric: str, unit: str) -> go.Figure | None:
    rows = db.history(conn, metric)
    if not rows or len(rows) < 2:
        return None
    df = pd.DataFrame([(r["ts"][:10], r["value"]) for r in rows], columns=["date", "v"])
    df = df.groupby("date", as_index=False)["v"].mean().sort_values("date")
    fig = go.Figure(go.Scatter(
        x=df["date"], y=df["v"], mode="lines+markers",
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


def _flow_frame(conn, reporter: int, flow: str):
    """Full partner x month matrix (kt) as a DataFrame; partners as rows (Gulf first,
    then by total desc), periods as YYYY-MM columns. Returns (df, gulf_pct_by_period)."""
    rows = db.flow_matrix(conn, reporter, flow)
    if not rows:
        return None, {}
    df = pd.DataFrame([(countries.name(r["partner_code"]), r["partner_code"],
                        r["period"][:4] + "-" + r["period"][4:], r["kt"]) for r in rows],
                      columns=["partner", "code", "month", "kt"])
    piv = df.pivot_table(index=["partner", "code"], columns="month", values="kt",
                         aggfunc="sum", fill_value=0.0)
    # Gulf share per month (importers only meaningful, computed regardless)
    gulf = {m: 0.0 for m in piv.columns}
    tot = {m: 0.0 for m in piv.columns}
    for (partner, code), row in piv.iterrows():
        for m in piv.columns:
            tot[m] += row[m]
            if code in countries.GULF:
                gulf[m] += row[m]
    gulf_pct = {m: (100 * gulf[m] / tot[m] if tot[m] else 0.0) for m in piv.columns}
    # order rows: Gulf first, then by total volume
    piv["_total"] = piv.sum(axis=1)
    piv["_gulf"] = [1 if c in countries.GULF else 0 for _, c in piv.index]
    piv = piv.sort_values(["_gulf", "_total"], ascending=[False, False]).drop(
        columns=["_total", "_gulf"])
    piv.index = [f"{'🛢 ' if c in countries.GULF else ''}{p}" for p, c in piv.index]
    return piv, gulf_pct


def _stacked_area(piv) -> go.Figure:
    """Stacked-area partner mix over time; top 10 partners named, rest 'Other'."""
    order = piv.sum(axis=1).sort_values(ascending=False)
    top = list(order.index[:10])
    fig = go.Figure()
    for name in top:
        fig.add_trace(go.Scatter(x=list(piv.columns), y=list(piv.loc[name]),
                                 mode="lines", stackgroup="one", name=name.replace("🛢 ", "")))
    other = piv.drop(index=top, errors="ignore")
    if len(other):
        fig.add_trace(go.Scatter(x=list(piv.columns), y=list(other.sum(axis=0)),
                                 mode="lines", stackgroup="one", name="Other",
                                 line=dict(color="#9aa0a6")))
    fig.update_layout(height=320, margin=dict(t=10, b=30, l=10, r=10),
                      legend=dict(font=dict(size=11)), plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)", yaxis_title="kt")
    return fig


def _trade_flows_section(conn) -> None:
    st.divider()
    st.subheader("Trade flows (Comtrade)")
    st.caption("Who sells sulfur to whom, by month (HS 2503). Importer partner = origin; "
               "exporter partner = destination. Mirror-derived, monthly, ~2-month lag — a "
               "missing month is non-reporting, not zero. Browse-only, not scored.")
    tabs = st.tabs([c["name"] for c in countries.TRADE_COUNTRIES])
    for tab, c in zip(tabs, countries.TRADE_COUNTRIES):
        with tab:
            piv, gulf_pct = _flow_frame(conn, c["reporter"], c["flow"])
            if piv is None:
                st.caption("no data yet — run `tracker trade-flows`")
                continue
            flow_word = "imports · origins" if c["flow"] == "M" else "exports · destinations"
            latest_m = piv.columns[-1]
            total = piv[latest_m].sum()
            cols = st.columns(3)
            cols[0].metric(f"{c['name']} {c['flow']=='M' and 'imports' or 'exports'}",
                           f"{total:.0f} kt", help=f"latest month {latest_m}")
            if c["flow"] == "M":
                cols[1].metric("Gulf share (latest)", f"{gulf_pct[latest_m]:.0f}%")
            st.caption(f"{flow_word} — full partner × month matrix (kt)")
            st.plotly_chart(_stacked_area(piv), use_container_width=True,
                            key=f"flow_area_{c['reporter']}_{c['flow']}")
            st.dataframe(piv.round(1), use_container_width=True)


main()
