from sulfur_tracker.collectors.fred_acid import parse_csv


def test_parse_fred_csv_skips_missing():
    text = ("observation_date,WPU0613020T1\n"
            "1987-06-01,100.0\n"
            "2026-05-01,712.3\n"
            "2026-06-01,.\n")           # FRED marks missing months with "."
    rows = parse_csv(text)
    assert rows[0] == ("1987-06-01", 100.0)
    assert rows[-1] == ("2026-05-01", 712.3)
    assert len(rows) == 2


def test_parse_fred_csv_legacy_date_header():
    rows = parse_csv("DATE,WPU0613020T1\n2020-01-01,305\n")
    assert rows == [("2020-01-01", 305.0)]
