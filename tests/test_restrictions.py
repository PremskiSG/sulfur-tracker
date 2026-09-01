from datetime import date

from sulfur_tracker import db, restrictions


def test_restricted_kt_respects_start_and_end(conn):
    db.upsert_restriction(conn, 398, "export_ban", "2026-06-27", None, 4600.0)
    db.upsert_restriction(conn, 792, "export_ban", "2026-04-07", "2026-09-30", 700.0)
    conn.commit()
    assert db.restricted_kt_on(conn, "2026-03-01") == 0.0          # before both
    assert db.restricted_kt_on(conn, "2026-05-01") == 700.0        # Turkey only
    assert db.restricted_kt_on(conn, "2026-07-01") == 5300.0       # both in force
    assert db.restricted_kt_on(conn, "2026-06-27") == 5300.0       # inclusive of start
    assert db.restricted_kt_on(conn, "2026-09-30") == 5300.0       # inclusive of end
    assert db.restricted_kt_on(conn, "2026-10-01") == 4600.0       # Turkey expired


def test_acid_measures_excluded_from_sulfur_maths(conn):
    db.upsert_restriction(conn, 398, "export_ban", "2026-06-27", None, 4600.0)
    db.upsert_restriction(conn, 156, "acid_export_ban", "2026-05-01", None, 4650.0,
                          commodity="acid")
    conn.commit()
    assert db.restricted_kt_on(conn, "2026-07-01") == 4600.0            # sulfur only
    assert db.restricted_kt_on(conn, "2026-07-01", commodity="acid") == 4650.0


def test_upsert_amends_rather_than_duplicates(conn):
    db.upsert_restriction(conn, 792, "export_ban", "2026-04-07", None, 700.0)
    db.upsert_restriction(conn, 792, "export_ban", "2026-04-07", "2026-09-30", 750.0)
    conn.commit()
    rows = db.restrictions(conn)
    assert len(rows) == 1
    assert rows[0]["end_date"] == "2026-09-30" and rows[0]["annual_kt"] == 750.0


def test_series_is_retroactive_and_rerunnable(conn):
    restrictions.seed_restrictions(conn)
    n1 = restrictions.restriction_series(conn, through=date(2026, 8, 31))
    assert n1 > 3                                    # months from first ban to Aug
    rows = db.history(conn, "supply_under_restriction_pct")
    assert len(rows) == n1
    assert rows[0]["value"] < rows[-1]["value"]      # restriction share grows over time
    n2 = restrictions.restriction_series(conn, through=date(2026, 8, 31))
    assert len(db.history(conn, "supply_under_restriction_pct")) == n2   # no duplicates
