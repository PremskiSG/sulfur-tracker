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
