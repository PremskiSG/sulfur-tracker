"""SQLite schema + write/read helpers. The signals and news tables are APPEND-ONLY:
every run inserts new rows and nothing is ever updated in place, so the full history
is preserved for sparklines and z-scores. news_items dedupes on url.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from sulfur_tracker.paths import db_path
from sulfur_tracker.signal import Signal

DDL = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  kind TEXT NOT NULL DEFAULT 'headline',   -- headline | collect | backfill | manual
  composite REAL,
  zone TEXT,
  coverage_pct REAL,
  contamination_flag TEXT
);

CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY,
  run_id INTEGER REFERENCES runs(id),
  source TEXT NOT NULL,
  metric TEXT NOT NULL,
  value REAL,
  unit TEXT,
  ts TEXT NOT NULL,                        -- observation timestamp (ISO-8601)
  direction_vs_baseline TEXT,
  confidence TEXT,
  staleness_days INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signals_metric_ts ON signals(metric, ts);

CREATE TABLE IF NOT EXISTS news_items (
  id INTEGER PRIMARY KEY,
  run_id INTEGER REFERENCES runs(id),
  ts TEXT NOT NULL,
  source TEXT,
  headline TEXT NOT NULL,
  url TEXT UNIQUE,
  classification TEXT,                     -- tightening | easing | neutral
  matched_keywords TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path is not None else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)
    conn.commit()
    return conn


def start_run(conn: sqlite3.Connection, kind: str = "headline") -> int:
    cur = conn.execute("INSERT INTO runs (kind) VALUES (?)", (kind,))
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn, run_id, composite=None, zone=None, coverage_pct=None,
               contamination_flag=None) -> None:
    conn.execute(
        "UPDATE runs SET composite=?, zone=?, coverage_pct=?, contamination_flag=? "
        "WHERE id=?",
        (composite, zone, coverage_pct, contamination_flag, run_id),
    )
    conn.commit()


def insert_signal(conn, run_id: int | None, sig: Signal) -> int:
    cur = conn.execute(
        "INSERT INTO signals (run_id, source, metric, value, unit, ts, "
        "direction_vs_baseline, confidence, staleness_days) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, sig.source, sig.metric, sig.value, sig.unit, sig.timestamp,
         sig.direction_vs_baseline, sig.confidence, sig.staleness_days),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_news(conn, run_id, ts, source, headline, url, classification,
                matched_keywords) -> bool:
    """Insert a news item; returns False if the url was already stored."""
    try:
        conn.execute(
            "INSERT INTO news_items (run_id, ts, source, headline, url, "
            "classification, matched_keywords) VALUES (?,?,?,?,?,?,?)",
            (run_id, ts, source, headline, url, classification, matched_keywords),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def history(conn, metric: str, days: int | None = None) -> list[sqlite3.Row]:
    """Observations for a metric ordered oldest->newest. If days is given, only
    rows within `days` of the most recent observation are returned (the trailing
    baseline window)."""
    rows = conn.execute(
        "SELECT ts, value, confidence, staleness_days FROM signals "
        "WHERE metric=? ORDER BY ts ASC",
        (metric,),
    ).fetchall()
    if not rows or days is None:
        return rows
    latest = rows[-1]["ts"]
    cutoff = conn.execute(
        "SELECT datetime(?, ?)", (latest, f"-{int(days)} days")
    ).fetchone()[0]
    return [r for r in rows if r["ts"] >= cutoff]


def latest_signal(conn, metric: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM signals WHERE metric=? ORDER BY ts DESC LIMIT 1", (metric,)
    ).fetchone()


def recent_news(conn, days: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM news_items WHERE ts >= datetime('now', ?) ORDER BY ts DESC",
        (f"-{int(days)} days",),
    ).fetchall()


def news_with_keyword(conn, keyword: str, days: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) c FROM news_items "
        "WHERE ts >= datetime('now', ?) AND "
        "(classification='tightening' AND matched_keywords LIKE ?)",
        (f"-{int(days)} days", f"%{keyword}%"),
    ).fetchone()
    return int(row["c"])


def signal_count(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) c FROM signals").fetchone()["c"])


def latest_run(conn) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM runs WHERE composite IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
