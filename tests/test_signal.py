import pytest

from sulfur_tracker.signal import (GROUPS, RELIABILITY, SIGNAL_SPEC, Direction,
                                   MetricSpec)


def test_every_spec_has_valid_group_and_direction():
    for spec in SIGNAL_SPEC.values():
        assert spec.group in GROUPS
        assert spec.reliability in RELIABILITY
        assert spec.higher_means in (Direction.TIGHTENING.value, Direction.EASING.value)
        assert spec.weight > 0


def test_sign_matches_direction():
    tightening = MetricSpec("m", "s", "demand", 2.0, "live",
                            Direction.TIGHTENING.value, "u", 7, "l")
    easing = MetricSpec("m", "s", "demand", 2.0, "live",
                        Direction.EASING.value, "u", 7, "l")
    assert tightening.sign == 1.0
    assert easing.sign == -1.0


def test_expected_metrics_present():
    for m in ["sulfur_price_cn", "indonesia_sulfur_imports_kt", "tampa_sulfur_cfr",
              "ksp_fob", "china_port_stocks_kt"]:
        assert m in SIGNAL_SPEC


def test_dropped_signals_absent():
    for m in ["news_tightening_score", "nickel_spread_vs_breakeven",
              "mhp_payables_pct", "hpal_rel_nickel"]:
        assert m not in SIGNAL_SPEC
    assert "demand" not in GROUPS


def test_default_weights_follow_base_times_reliability():
    # Signals without a documented adjustment equal group_base x reliability_factor.
    for metric in ("sulfur_price_cn", "china_port_stocks_kt", "tampa_sulfur_cfr",
                   "gulf_sulfur_transits_wk"):
        s = SIGNAL_SPEC[metric]
        assert s.weight == pytest.approx(GROUPS[s.group][2] * RELIABILITY[s.reliability])
