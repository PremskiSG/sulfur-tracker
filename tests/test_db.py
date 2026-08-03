from sulfur_tracker import db
from sulfur_tracker.signal import Signal


def _sig(metric, value, ts, unit="x"):
    return Signal("t", metric, value, unit, ts)


def test_signals_are_append_only(conn):
    rid = db.start_run(conn, "collect")
    db.insert_signal(conn, rid, _sig("m", 1.0, "2026-07-01"))
    db.insert_signal(conn, rid, _sig("m", 2.0, "2026-07-02"))
    rows = db.history(conn, "m")
    assert [r["value"] for r in rows] == [1.0, 2.0]  # both kept, ordered by ts


def test_history_window_filters_by_latest(conn):
    rid = db.start_run(conn, "collect")
    db.insert_signal(conn, rid, _sig("m", 1.0, "2026-01-01"))
    db.insert_signal(conn, rid, _sig("m", 2.0, "2026-06-01"))
    db.insert_signal(conn, rid, _sig("m", 3.0, "2026-06-20"))
    window = db.history(conn, "m", days=90)  # relative to 2026-06-20
    assert [r["value"] for r in window] == [2.0, 3.0]


def test_news_dedupe_on_url(conn):
    rid = db.start_run(conn, "collect")
    assert db.insert_news(conn, rid, "2026-07-01", "s", "h", "http://a", "tightening", "curtailment")
    assert not db.insert_news(conn, rid, "2026-07-01", "s", "h", "http://a", "tightening", "x")


def test_trade_flow_upsert_is_idempotent(conn):
    db.upsert_flow(conn, 360, "M", 784, "202603", 110.0)
    db.upsert_flow(conn, 360, "M", 784, "202603", 111.5)   # same key -> replaces
    conn.commit()
    rows = db.flow_matrix(conn, 360, "M")
    assert len(rows) == 1
    assert rows[0]["kt"] == 111.5


def test_flow_matrix_and_periods(conn):
    for partner, period, kt in [(784, "202602", 35.1), (784, "202603", 110.0),
                                (682, "202603", 95.4)]:
        db.upsert_flow(conn, 360, "M", partner, period, kt)
    conn.commit()
    assert db.flow_periods(conn, 360, "M") == ["202602", "202603"]
    assert len(db.flow_matrix(conn, 360, "M")) == 3
    assert db.flow_matrix(conn, 842, "X") == []          # other reporter unaffected
    assert db.flow_count(conn) == 3


def test_latest_signal(conn):
    rid = db.start_run(conn, "collect")
    db.insert_signal(conn, rid, _sig("m", 1.0, "2026-07-01"))
    db.insert_signal(conn, rid, _sig("m", 9.0, "2026-07-05"))
    assert db.latest_signal(conn, "m")["value"] == 9.0
