from pathlib import Path

from sulfur_tracker.collectors._tradingeconomics import parse_te_headline
from sulfur_tracker.collectors.sulfur_price_cn import SulfurPriceCN

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_te_sulfur_headline():
    html = (FIXTURES / "te_sulfur.html").read_text(encoding="utf-8")
    sig = SulfurPriceCN().parse(html)
    assert sig.metric == "sulfur_price_cn"
    assert sig.value == 8569.0
    assert sig.unit == "CNY/t"
    assert sig.timestamp == "2026-07-08"
    assert sig.confidence == "high"


def test_parse_te_sulfur_yoy():
    html = (FIXTURES / "te_sulfur.html").read_text(encoding="utf-8")
    h = parse_te_headline(html, "sulfur")
    # blurb: "still 270.79% higher than a year ago"
    assert h.yoy_pct == 270.79
