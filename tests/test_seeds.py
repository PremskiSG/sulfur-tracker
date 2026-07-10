from sulfur_tracker import db, seeds


def test_backfill_seeds_and_is_idempotent(conn):
    n1 = seeds.backfill(conn)
    assert n1 == len(seeds.SEED_ROWS)
    before = db.signal_count(conn)
    n2 = seeds.backfill(conn)               # second call is a no-op
    assert n2 == 0
    assert db.signal_count(conn) == before


def test_backfill_force_reseeds(conn):
    seeds.backfill(conn)
    n = seeds.backfill(conn, force=True)
    assert n == len(seeds.SEED_ROWS)


def test_seeded_metrics_are_scoreable(conn):
    seeds.backfill(conn)
    ksp = db.history(conn, "ksp_fob")
    assert [r["value"] for r in ksp] == [805.0, 950.0]
