# sulfur-tracker

A bi-weekly composite view of the **2026 Strait of Hormuz sulfur supply disruption**,
built from **downstream receiving-end signals** rather than unreliable strait-level
data. Sulfur is a refinery byproduct — supply cannot respond to price — and ~50% of
seaborne trade transits Hormuz. The marginal buyer is Indonesian HPAL nickel processing
(Morowali/IMIP ~93% Gulf-dependent, Obi ~89%, Weda Bay ~64%).

The tracker answers one question every two weeks: **is the sulfur situation tightening,
stable, or easing?** — as a −100..+100 composite with labeled zones, per-signal
contributions, and prominent staleness/coverage reporting.

## Why bi-weekly

The physical signals refresh slowly (port stocks weekly, imports & FOB prices monthly,
MHP payables weekly) and the causal chain runs in weeks:

```
strait event → 2–4 wk → port arrivals → 2–6 wk → inventory exhaustion
             → production curtailment → price/payables → 4–12 wk → company disclosures
```

A daily verdict would be mostly noise. `tracker run` is the fortnightly headline;
`tracker collect --fast` can run daily to densify the fast signals (price, nickel,
news, equities) so the 90-day z-scores have enough points.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
tracker backfill          # seed known 2026 baselines so nothing is empty
tracker history           # backfill REAL history (Comtrade imports + NCKL.JK), ~1 min
tracker run               # collect → score → write report → print summary
tracker dashboard         # launch the Streamlit dashboard
pytest                    # run the test suite
```

The dashboard tracks each signal as a **price with its historical trend line**, grouped
by tier, with reference prices (LME nickel, NCKL.JK) and a slim composite readout at the
**bottom** (no gauge). CNY prices show a live USD equivalent in parentheses. `tracker
history` seeds genuine multi-month trends where a free source exists — **Indonesia
imports** (Comtrade) and **NCKL.JK** (yfinance). The news feed was removed from the
dashboard (free RSS returns stale, relevance-ranked results); news is still collected
with a 30-day recency filter purely to drive the contamination check.

**No free historical series exists** for China sulfur port stocks (SMM/Longzhong
paywalled; SunSirs is price, not inventory), Gulf laden departures (AIS is paid;
Comtrade Gulf exports are Saudi-only and stop mid-2025), or the Mideast FOB/MHP prices.
China's own Comtrade imports were evaluated as a proxy but the free preview stops
reporting China around end-2024. These signals stay **manual-entry** and build history
as you enter values; Indonesia imports (the ~90% Gulf-dependent marginal buyer) carries
the physical-flow trend.

Manual entry for the credential-free / paywalled signals:

```bash
tracker input china_ports 210     # China port stocks (kt)
tracker input ais 12              # Gulf laden departures (vessels/week)
tracker input ksp 950             # Kuwait KSP FOB (USD/t)
tracker input adnoc_osp 1000      # Adnoc OSP FOB (USD/t)
tracker input mhp_payables 78     # MHP payables (% of LME nickel)
```

## Composite

Per signal: z-score vs the trailing 90-day baseline, **direction-normalized so positive
= tightening**, weighted by tier (Tier 1 = 3×, Tier 2 = 2×, Tier 3 = 1×), averaged over
available signals and scaled to −100..+100. Zones: `easing` / `stable` / `tightening` /
`acute` (+ `acute-easing`). Coverage % = available weight ÷ total weight, so a composite
built on thin or stale data says so.

**Contamination check** (Indonesia is a noisy sensor — cuts are also driven by RKAB ore
quotas): if imports are falling *and* there is no curtailment news, the tracker flags
*"inventory drawdown phase — curtailments expected in 30–60 days."* Falling imports +
curtailment news = sulfur-driven; output cut + rising imports = policy, not sulfur.

## Signals

| Signal | Tier | Cadence | Source (free) | Lag vs strait event | Main failure modes | Best paid upgrade |
|---|---|---|---|---|---|---|
| China port inventory | 1 | weekly | SMM/Longzhong (login) → **manual** | ~4–8 wk | login wall; manual staleness | **SMM** — direct weekly port-stock series |
| China sulfur price | 1 | daily | tradingeconomics (scrape) | ~2–6 wk | TE layout change; CN holiday gaps | **SMM/Longzhong** — spot + regional basis |
| Gulf AIS transits | 1 | weekly | AIS provider → **manual** | ~2–4 wk (leading) | no key; polygon/vessel-filter noise | **Kpler** — actual sulfur tonnage & ETAs |
| Indonesia imports | 1 | monthly | UN Comtrade v1 (API) | ~8–12 wk (lagged) | ~2-mo reporting lag; missing months | **Kpler** — real-time cargo tracking |
| Kuwait KSP FOB | 2 | monthly | trade press → **manual** | ~2–4 wk | announced irregularly | **Argus** — official price feed |
| Adnoc OSP FOB | 2 | monthly | trade press → **manual** | ~2–4 wk | announced irregularly | **Argus** — official price feed |
| Nickel vs break-even | 2 | daily | tradingeconomics (scrape) | leading (demand) | break-even is an assumption | **Argus/CRU** — HPAL cost curves |
| MHP payables | 2 | weekly | SMM/Argus → **manual** | ~2–4 wk | paywalled; manual staleness | **SMM/Argus** — payables series |
| News monitor | 3 | ~daily | mining.com + Google News RSS | co-incident | keyword false-positives; no LLM | **Argus/Kpler** editorial feeds |
| Equity basket | 3 | daily | yfinance (+ Stooq) | leading (sentiment) | Yahoo 429; beta/FX swamp signal | intraday equity + nickel data |

The two highest-value paid upgrades are **Kpler** (turns the two weakest live signals —
AIS transits and Indonesia imports — into real-time cargo tonnage, removing the
2–3 month Comtrade lag) and **Argus** (replaces manual FOB/payables entry with an
authoritative price feed). **SMM** most improves the single best physical proxy, China
port inventory.

## Cron

```cron
# Fortnightly headline (collect + score + report + dashboard reflects it)
0 8 */14 * *  cd /path/to/sulfur_tracker && .venv/bin/tracker run
# Optional: densify the fast signals daily
0 7 * * *     cd /path/to/sulfur_tracker && .venv/bin/tracker collect --fast
```

## Architecture

- `sulfur_tracker/signal.py` — normalized `Signal` + `SIGNAL_SPEC` (tier, direction, cadence).
- `sulfur_tracker/db.py` — append-only SQLite (history never overwritten).
- `sulfur_tracker/scoring.py` — z-score composite, coverage, zones, contamination check.
- `sulfur_tracker/collectors/` — one module per source; all degrade gracefully.
- `sulfur_tracker/seeds.py` — `tracker backfill` baselines.
- `sulfur_tracker/dashboard.py` — Streamlit dashboard (plotly gauge + sparklines).
- `config.yaml` — thresholds, weights, baselines, per-collector enable; `secrets.yaml` — optional keys.
