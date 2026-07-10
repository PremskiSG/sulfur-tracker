import json

from sulfur_tracker import db, history
from sulfur_tracker.seeds import backfill


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
