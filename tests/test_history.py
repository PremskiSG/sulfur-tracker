import json
from datetime import date

from sulfur_tracker import db, history
from sulfur_tracker.seeds import backfill
from sulfur_tracker.collectors.indonesia_imports import _shift_month


def _write(tmp_path, data, unit="CNY/T"):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"unit": unit, "data": data}), encoding="utf-8")
    return str(p)


def test_import_price_json_inserts_points(conn, tmp_path):
    path = _write(tmp_path, [{"date": "2025-08-01", "price": 2474.33},
                             {"date": "2025-08-15", "price": 2627.67}])
    assert history.import_price_json(conn, path) == 2
    rows = db.history(conn, "sulfur_price_cn")
    assert [r["value"] for r in rows] == [2474.33, 2627.67]


def test_import_is_idempotent(conn, tmp_path):
    path = _write(tmp_path, [{"date": "2025-08-01", "price": 2474.33}])
    history.import_price_json(conn, path)
    history.import_price_json(conn, path)  # re-import drops prior te_history
    assert len(db.history(conn, "sulfur_price_cn")) == 1


def test_import_supersedes_placeholder_seeds(conn, tmp_path):
    backfill(conn)  # seeds placeholder sulfur_price_cn points
    path = _write(tmp_path, [{"date": "2025-08-01", "price": 100.0}])
    history.import_price_json(conn, path)
    srcs = {r["source"] for r in conn.execute(
        "SELECT DISTINCT source FROM signals WHERE metric='sulfur_price_cn'").fetchall()}
    assert "seed" not in srcs and "te_history" in srcs


def test_comtrade_replaces_customs_remainder_for_same_month(conn, monkeypatch):
    year, month = _shift_month(date.today().year, date.today().month, -2)
    period = f"{year}{month:02d}"
    db.upsert_flow(conn, 360, "M", 784, period, 100.0, source="smm")
    db.upsert_flow(conn, 360, "M", 899, period, 21.0, source="smm")
    conn.commit()

    def fetched(reporter, flow, fetched_period):
        if reporter == 360 and flow == "M" and fetched_period == period:
            return {784: 100.0, 124: 50.0}
        return {}

    monkeypatch.setattr("sulfur_tracker.collectors.comtrade_flows.fetch_flows", fetched)
    history.backfill_trade_flows(conn, months=1, lag=2)
    rows = conn.execute(
        "SELECT partner_code, source FROM trade_flows WHERE reporter=360 "
        "AND flow='M' AND period=? ORDER BY partner_code", (period,),
    ).fetchall()
    assert [(r["partner_code"], r["source"]) for r in rows] == [
        (124, "comtrade"), (784, "comtrade")]


def test_trade_flows_can_refresh_poland_only(conn, monkeypatch):
    calls = []

    def fetched(reporter, flow, period):
        calls.append((reporter, flow, period))
        return {40: 2.7} if reporter == 616 else {}

    monkeypatch.setattr("sulfur_tracker.collectors.comtrade_flows.fetch_flows", fetched)
    counts = history.backfill_trade_flows(conn, months=2, lag=1, country="Poland")
    assert counts == {"Poland": 2}
    assert len(calls) == 2
    assert all(reporter == 616 and flow == "X" for reporter, flow, _ in calls)
    assert len(db.flow_matrix(conn, 616, "X")) == 2
