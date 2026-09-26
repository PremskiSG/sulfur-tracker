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


def test_parse_te_flat_day():
    """On an unchanged day TE writes "traded flat at", which broke the parser on
    2026-09-26. The value must still be read, with no daily change."""
    html = ("<p>Sulfur - Summary Sulfur traded flat at 7,719 CNY/T on September 25, "
            "2026. Over the past month, Sulfur's price has fallen 15.20%, but it is "
            "still 192.64% higher than a year ago, according to trading on a "
            "contract for difference (CFD).</p>")
    h = parse_te_headline(html, "sulfur")
    assert (h.value, h.unit, h.date_iso) == (7719.0, "CNY/t", "2026-09-25")
    assert h.change_pct is None
    assert h.yoy_pct == 192.64


def test_parse_te_sulfur_yoy():
    html = (FIXTURES / "te_sulfur.html").read_text(encoding="utf-8")
    h = parse_te_headline(html, "sulfur")
    # blurb: "still 270.79% higher than a year ago"
    assert h.yoy_pct == 270.79
