from sulfur_tracker import db, seeds


def _expected_rows() -> int:
    """SEED_ROWS plus the implied-sulfur-demand rows derived from each MHP point."""
    mhp = sum(1 for r in seeds.SEED_ROWS if r[0] == "indonesia_mhp_output_kt_ni")
    return len(seeds.SEED_ROWS) + mhp


def test_backfill_seeds_and_is_idempotent(conn):
    n1 = seeds.backfill(conn)
    assert n1 == _expected_rows()
    before = db.signal_count(conn)
    n2 = seeds.backfill(conn)               # second call is a no-op
    assert n2 == 0
    assert db.signal_count(conn) == before


def test_backfill_force_reseeds(conn):
    seeds.backfill(conn)
    n = seeds.backfill(conn, force=True)
    assert n == _expected_rows()


def test_seeded_metrics_are_scoreable(conn):
    seeds.backfill(conn)
    ksp = db.history(conn, "ksp_fob")
    assert [r["value"] for r in ksp] == [805.0, 950.0]
