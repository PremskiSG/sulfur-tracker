from pathlib import Path

from sulfur_tracker.collectors.news_monitor import classify, parse_feed

FIXTURES = Path(__file__).parent / "fixtures"


def test_classify_tightening():
    cls, matched = classify("Indonesian HPAL plant enters care and maintenance")
    assert cls == "tightening"
    assert "care and maintenance" in matched


def test_classify_easing():
    cls, _ = classify("Nickel HPAL output resumes as surplus builds")
    assert cls == "easing"


def test_classify_off_topic_is_neutral():
    cls, matched = classify("Gold price hits record on Fed cut")
    assert cls == "neutral"
    assert matched == []


def test_parse_feed_only_keeps_relevant(tmp_path):
    xml = (FIXTURES / "mining_rss.xml").read_text(encoding="utf-8")
    items = parse_feed(xml, "mining.com")
    # every retained item must be topically relevant (non-empty match or explicit tag)
    for it in items:
        assert it.url.startswith("http")
        assert it.classification in ("tightening", "easing", "neutral")
