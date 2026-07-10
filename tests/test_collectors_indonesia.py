import json
from pathlib import Path

from sulfur_tracker.collectors.indonesia_imports import _months_back, world_kt
from datetime import date

FIXTURES = Path(__file__).parent / "fixtures"


def test_world_kt_from_comtrade_fixture():
    payload = json.loads((FIXTURES / "comtrade_360_2503.json").read_text())
    # World row (partnerCode 0) netWgt 580,145,706 kg -> 580.1 kt
    assert world_kt(payload) == 580.1


def test_world_kt_falls_back_to_partner_sum():
    payload = {"data": [{"partnerCode": 156, "netWgt": 1_000_000},
                        {"partnerCode": 842, "netWgt": 2_000_000}]}
    assert world_kt(payload) == 3.0


def test_world_kt_empty():
    assert world_kt({"data": []}) is None


def test_months_back_wraps_year():
    assert _months_back(date(2026, 2, 28), 3) == ["202602", "202601", "202512"]
