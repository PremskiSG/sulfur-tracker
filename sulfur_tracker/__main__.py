"""sulfur-tracker CLI. Entry point `tracker`.

    tracker run                 bi-weekly headline: collect -> score -> report
    tracker collect [--fast]    collect stage only (--fast = daily-updating signals)
    tracker score               recompute + print composite from stored history
    tracker report              (re)write today's markdown report
    tracker backfill [--force]  seed known 2026 baselines
    tracker input <src> <val>   manual entry (china_ports|ais|ksp|adnoc_osp|tampa_sulfur)
    tracker dashboard           launch the Streamlit dashboard
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import date

from sulfur_tracker import db, history, report, seeds
from sulfur_tracker.collectors import MANUAL_INPUTS, collect_all
from sulfur_tracker.collectors.base import staleness_days
from sulfur_tracker.config import load_config
from sulfur_tracker.paths import dashboard_module
from sulfur_tracker.scoring import ScoreResult, score
from sulfur_tracker.secrets import load_secrets
from sulfur_tracker.signal import Confidence, Signal

log = logging.getLogger("sulfur_tracker")

ZONE_LABEL = {
    "acute": "ACUTE TIGHTENING", "tightening": "TIGHTENING", "stable": "STABLE",
    "easing": "EASING", "acute-easing": "ACUTE EASING",
}


def _print_summary(result: ScoreResult) -> None:
    print()
    print(f"  COMPOSITE  {result.composite:+6.1f}   [{ZONE_LABEL.get(result.zone, result.zone)}]")
    print(f"  coverage   {result.coverage_pct:5.1f}%   max staleness {result.max_staleness_days}d")
    if result.contamination_flag:
        print(f"  ! {result.contamination_flag}")
    if result.groups:
        print()
        print("  where it's coming from:  " + "   ".join(
            f"{g.label} {g.contribution:+.1f}" for g in result.groups))
    from sulfur_tracker.signal import GROUPS
    order = {k: v[0] for k, v in GROUPS.items()}
    print()
    print(f"  {'signal':<34}{'value':>16}{'z':>8}{'contrib':>9}{'stale':>7}")
    print("  " + "-" * 74)
    last_group = None
    for s in sorted(result.signals, key=lambda x: (order.get(x.group, 9), -abs(x.contribution))):
        if s.group != last_group:
            print(f"  [{GROUPS.get(s.group, (0, s.group))[1]}]")
            last_group = s.group
        if s.available:
            val = f"{s.value:g} {s.unit}"
            stale = f"{s.staleness_days}{'!' if s.stale else ''}"
            print(f"  {s.label:<34}{val:>16}{s.z:>+8.2f}"
                  f"{s.contribution:>+9.2f}{stale:>7}")
        else:
            print(f"  {s.label:<34}{'no data':>16}{'-':>8}{'-':>9}{'-':>7}")
    print()


def cmd_collect(conn, cfg, secrets, fast: bool) -> int:
    run_id = db.start_run(conn, kind="collect")
    outcomes = collect_all(conn, run_id, cfg, secrets, fast=fast)
    db.finish_run(conn, run_id)
    for o in outcomes:
        note = f"  ({o.note})" if o.note else ""
        print(f"  {o.name:<24} {o.signals} signals, {o.news} news{note}")
    return run_id


def cmd_run(conn, cfg, secrets) -> int:
    run_id = db.start_run(conn, kind="headline")
    collect_all(conn, run_id, cfg, secrets, fast=False)
    result = score(conn)
    db.finish_run(conn, run_id, result.composite, result.zone,
                  result.coverage_pct, result.contamination_flag)
    path = report.write_report(result, conn)
    _print_summary(result)
    print(f"  report: {path}")
    return 0


def cmd_input(conn, alias: str, value: float, on: str | None, unit: str | None) -> int:
    if alias not in MANUAL_INPUTS:
        print(f"unknown input '{alias}'. choices: {', '.join(MANUAL_INPUTS)}",
              file=sys.stderr)
        return 2
    metric, default_unit, source = MANUAL_INPUTS[alias]
    ts = on or date.today().isoformat()
    run_id = db.start_run(conn, kind="manual")
    sig = Signal(source=source, metric=metric, value=float(value),
                 unit=unit or default_unit, timestamp=ts,
                 confidence=Confidence.MANUAL.value, staleness_days=staleness_days(ts))
    db.insert_signal(conn, run_id, sig)
    db.finish_run(conn, run_id)
    print(f"  stored manual {metric} = {value} {unit or default_unit} @ {ts}")
    return 0


def cmd_dashboard() -> int:
    try:
        return subprocess.call(["streamlit", "run", str(dashboard_module())])
    except FileNotFoundError:
        print("streamlit not installed. `pip install -e .` then retry.", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tracker", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("run", help="bi-weekly headline: collect + score + report")
    c = sub.add_parser("collect", help="collect signals only")
    c.add_argument("--fast", action="store_true",
                   help="only daily-updating signals (price, nickel, news, equities)")
    sub.add_parser("score", help="recompute + print composite from stored history")
    sub.add_parser("report", help="(re)write today's markdown report")
    b = sub.add_parser("backfill", help="seed known 2026 baseline datapoints")
    b.add_argument("--force", action="store_true", help="re-seed even if already done")
    h = sub.add_parser("history", help="backfill REAL historical series (Comtrade + NCKL.JK)")
    h.add_argument("--months", type=int, default=18, help="months of history to pull")
    ip = sub.add_parser("import-prices", help="import a JSON price-history file")
    ip.add_argument("path", help="path to JSON: {'unit':..,'data':[{'date','price'},..]}")
    ip.add_argument("--metric", default="sulfur_price_cn")
    sub.add_parser("scan-prices",
                   help="LLM scan of news for KSP/Adnoc prices (needs DeepSeek key)")
    i = sub.add_parser("input", help="manual data entry")
    i.add_argument("source", choices=list(MANUAL_INPUTS))
    i.add_argument("value", type=float)
    i.add_argument("--date", dest="on", help="observation date YYYY-MM-DD (default today)")
    i.add_argument("--unit", help="override the default unit")
    sub.add_parser("dashboard", help="launch the Streamlit dashboard")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    args = build_parser().parse_args(argv)

    if args.cmd == "dashboard":
        return cmd_dashboard()

    cfg = load_config()
    secrets = load_secrets()
    conn = db.connect()

    if args.cmd == "run":
        return cmd_run(conn, cfg, secrets)
    if args.cmd == "collect":
        cmd_collect(conn, cfg, secrets, fast=args.fast)
        _print_summary(score(conn))
        return 0
    if args.cmd == "backfill":
        n = seeds.backfill(conn, force=args.force)
        print(f"  backfill: {n} seed datapoints inserted")
        return 0
    if args.cmd == "history":
        print(f"  fetching {args.months} months of history (Comtrade is slow)...")
        counts = history.backfill_history(conn, months=args.months)
        for k, v in counts.items():
            print(f"  history {k}: {v} points")
        return 0
    if args.cmd == "import-prices":
        n = history.import_price_json(conn, args.path, metric=args.metric)
        print(f"  imported {n} price points into {args.metric}")
        return 0
    if args.cmd == "scan-prices":
        from sulfur_tracker.collectors.llm_price_scan import LlmPriceScan
        ccfg = cfg.get("collectors", {}).get("llm_price_scan", {}) or {}
        inst = LlmPriceScan(ccfg, secrets, conn=conn)
        run_id = db.start_run(conn, "collect")
        res = inst.safe_run()
        for s in res.signals:
            db.insert_signal(conn, run_id, s)
        db.finish_run(conn, run_id)
        for s in res.signals:
            print(f"  {s.metric} = {s.value} {s.unit} @ {s.timestamp}")
        print(f"  scan-prices: {len(res.signals)} price(s)"
              + (f" — {res.note}" if res.note else ""))
        return 0
    if args.cmd == "input":
        return cmd_input(conn, args.source, args.value, args.on, args.unit)
    if args.cmd == "report":
        result = score(conn)
        path = report.write_report(result, conn)
        print(f"  report: {path}")
        return 0
    # default (no subcommand) or `score`: print the current composite
    _print_summary(score(conn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
