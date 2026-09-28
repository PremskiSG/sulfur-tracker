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


def test_flow_source_defaults_to_comtrade_and_is_reported(conn):
    """A month filled from a national customs release must not read as Comtrade."""
    db.upsert_flow(conn, 360, "M", 784, "202606", 109.3)
    db.upsert_flow(conn, 360, "M", 784, "202607", 256.8, source="smm")
    conn.commit()
    assert db.flow_sources(conn, 360, "M") == {"202606": "comtrade", "202607": "smm"}


def test_flow_upsert_updates_source(conn):
    """When Comtrade finally files a month, it overwrites the stand-in and its label."""
    db.upsert_flow(conn, 360, "M", 784, "202607", 256.8, source="smm")
    db.upsert_flow(conn, 360, "M", 784, "202607", 255.0)
    conn.commit()
    assert db.flow_sources(conn, 360, "M") == {"202607": "comtrade"}
    assert db.flow_matrix(conn, 360, "M")[0]["kt"] == 255.0


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


def test_identical_observation_is_not_stored_twice(conn):
    """Re-collecting an unchanged upstream print must not double-count the day."""
    s = Signal("te", "sulfur_price_cn", 7719.0, "CNY/t", "2026-09-25")
    first = db.insert_signal(conn, None, s)
    again = db.insert_signal(conn, None, s)
    assert again == first
    assert len(db.history(conn, "sulfur_price_cn")) == 1


def test_revised_value_for_same_date_is_appended(conn):
    """A corrected value for the same date is real new information, so it is kept."""
    db.insert_signal(conn, None, Signal("te", "sulfur_price_cn", 7719.0, "CNY/t",
                                        "2026-09-25"))
    db.insert_signal(conn, None, Signal("te", "sulfur_price_cn", 7700.0, "CNY/t",
                                        "2026-09-25"))
    assert [r["value"] for r in db.history(conn, "sulfur_price_cn")] == [7719.0, 7700.0]
