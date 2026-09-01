from sulfur_tracker import db
from sulfur_tracker.scoring import score
from sulfur_tracker.signal import Signal


def _insert_series(conn, metric, values, start="2026-07-01"):
    rid = db.start_run(conn, "collect")
    y, m, d = (int(x) for x in start.split("-"))
    for i, v in enumerate(values):
        ts = f"2026-07-{d + i:02d}"
        db.insert_signal(conn, rid, Signal("t", metric, float(v), "u", ts))


def test_rising_price_reads_as_tightening(conn):
    _insert_series(conn, "sulfur_price_cn", [100, 100, 100, 200])
    r = score(conn)
    price = next(s for s in r.signals if s.metric == "sulfur_price_cn")
    assert price.z > 0                       # higher price = tightening
    assert r.composite > 0
    assert r.zone in ("tightening", "acute")
    assert 0 < r.coverage_pct < 100          # only one metric present


def test_rising_port_stocks_reads_as_easing(conn):
    _insert_series(conn, "china_port_stocks_kt", [100, 100, 100, 300])
    r = score(conn)
    stocks = next(s for s in r.signals if s.metric == "china_port_stocks_kt")
    assert stocks.z < 0                       # more stock = easing
    assert r.composite < 0
    assert r.zone in ("easing", "acute-easing")


def test_coverage_is_zero_when_empty(conn):
    r = score(conn)
    assert r.coverage_pct == 0.0
    assert r.composite == 0.0
    assert not r.available_signals


def test_contamination_flag_when_imports_fall_without_curtailment_news(conn):
    _insert_series(conn, "indonesia_sulfur_imports_kt", [966, 966, 700])
    r = score(conn)
    assert r.contamination_flag is not None
    assert "inventory drawdown" in r.contamination_flag.lower()


def test_contamination_cleared_by_curtailment_news(conn):
    from sulfur_tracker.collectors.base import now_iso
    _insert_series(conn, "indonesia_sulfur_imports_kt", [966, 966, 700])
    rid = db.start_run(conn, "collect")
    db.insert_news(conn, rid, now_iso(), "s", "HPAL curtailment begins",
                   "http://x", "tightening", "curtailment")
    r = score(conn)
    assert r.contamination_flag is None


def _falling_imports(conn):
    """Indonesia imports falling -> the precondition for the contamination check."""
    _insert_series(conn, "indonesia_sulfur_imports_kt", [966, 966, 700])


def test_measured_mhp_decline_reports_confirmed_curtailment(conn, monkeypatch):
    import sulfur_tracker.scoring as sc
    _falling_imports(conn)
    rid = db.start_run(conn, "collect")
    for val, ts in [(42.0, "2026-07-01"), (29.9, "2026-07-05")]:
        db.insert_signal(conn, rid, Signal("t", "indonesia_mhp_output_kt_ni", val,
                                           "kt Ni", ts))
    monkeypatch.setattr(sc, "_mhp_decline", lambda conn, cc: 28.8)
    r = score(conn)
    assert r.contamination_flag is not None
    assert "curtailments confirmed" in r.contamination_flag.lower()


def test_stale_mhp_falls_back_to_news_rule(conn):
    """An MHP point far in the past must not be trusted; the keyword rule takes over."""
    _falling_imports(conn)
    rid = db.start_run(conn, "collect")
    for val, ts in [(42.0, "2020-01-31"), (29.9, "2020-06-30")]:
        db.insert_signal(conn, rid, Signal("t", "indonesia_mhp_output_kt_ni", val,
                                           "kt Ni", ts))
    r = score(conn)
    assert r.contamination_flag is not None
    assert "inventory drawdown" in r.contamination_flag.lower()
