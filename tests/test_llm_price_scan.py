from sulfur_tracker.collectors import llm_price_scan as lps
from sulfur_tracker.collectors.llm_price_scan import LlmPriceScan
from sulfur_tracker.llm import parse_json


def test_parse_json_strips_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('here is data {"ksp_fob": {"price": 950}} end')["ksp_fob"]["price"] == 950


def test_degrades_without_key(monkeypatch):
    monkeypatch.setattr(lps.llm, "has_key", lambda: False)
    res = LlmPriceScan().collect()
    assert res.signals == []
    assert "manual entry" in res.note


def test_extracts_prices_from_llm(monkeypatch):
    monkeypatch.setattr(lps.llm, "has_key", lambda: True)
    monkeypatch.setattr(lps, "_recent_titles",
                        lambda url, days: [("Kuwait sets July sulphur KSP at $950/t", "2026-07-02")])
    monkeypatch.setattr(lps.llm, "extract",
                        lambda *a, **k: {"ksp_fob": {"price": 950, "date": "2026-07"},
                                         "adnoc_osp_fob": {"price": None, "date": None}})
    res = LlmPriceScan().collect()
    by = {s.metric: s for s in res.signals}
    assert by["ksp_fob"].value == 950.0
    assert by["ksp_fob"].unit == "USD/t"
    assert by["ksp_fob"].timestamp == "2026-07-15"      # YYYY-MM -> mid-month
    assert "adnoc_osp_fob" not in by                      # null skipped, not guessed
    assert res.signals[0].confidence == "medium"


def test_weekly_rerun_skips_unchanged_price(monkeypatch, conn):
    monkeypatch.setattr(lps.llm, "has_key", lambda: True)
    monkeypatch.setattr(lps, "_recent_titles", lambda url, days: [("KSP $950", "2026-07-02")])
    monkeypatch.setattr(lps.llm, "extract",
                        lambda *a, **k: {"ksp_fob": {"price": 950, "date": "2026-07"}})
    from sulfur_tracker import db
    inst = LlmPriceScan(cfg={"targets": {"ksp_fob": ("KSP", "q", "USD/t")}},
                        conn=conn)
    first = inst.collect()
    assert len(first.signals) == 1
    db.insert_signal(conn, None, first.signals[0])   # persist it
    second = inst.collect()                            # same price next week
    assert second.signals == []                        # no duplicate
    assert "0 new, 1 unchanged" in second.note


def test_bad_llm_json_is_caught(monkeypatch):
    monkeypatch.setattr(lps.llm, "has_key", lambda: True)
    monkeypatch.setattr(lps, "_recent_titles", lambda url, days: [("x", "2026-07-01")])
    def boom(*a, **k):
        raise ValueError("no JSON object in response")
    monkeypatch.setattr(lps.llm, "extract", boom)
    res = LlmPriceScan().collect()
    assert res.signals == []
    assert "failed" in res.note
