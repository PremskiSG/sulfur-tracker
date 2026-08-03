from sulfur_tracker import countries


def test_name_known_and_fallback():
    assert countries.name(784) == "UAE"
    assert countries.name(360) == "Indonesia"
    assert countries.name(99999) == "code 99999"


def test_gulf_membership():
    for code in (784, 682, 634, 414, 48, 512):
        assert countries.is_gulf(code)
    for code in (124, 842, 398, 360):        # Canada, USA, Kazakhstan, Indonesia
        assert not countries.is_gulf(code)


def test_trade_countries_config():
    names = [c["name"] for c in countries.TRADE_COUNTRIES]
    assert names == ["Indonesia", "Morocco", "India", "Brazil", "USA", "Canada"]
    for c in countries.TRADE_COUNTRIES:
        assert c["flow"] in ("M", "X")
        assert isinstance(c["reporter"], int)
