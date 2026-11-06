"""The transcribed official odds must agree with the game's combinatorics."""
from math import comb

from m4l import config


def combinatorial_odds(whites, mb):
    total = comb(58, 5) * 5
    ways = comb(5, whites) * comb(53, 5 - whites) * (1 if mb else 4)
    return total / ways


def test_nine_tiers_best_first():
    assert config.TIER_CODES == ["m5-mb", "m5", "m4-mb", "m4", "m3-mb", "m3", "m2-mb", "m2", "m1-mb"]


def test_official_odds_match_combinatorics():
    for t in config.PRIZE_TIERS:
        assert round(combinatorial_odds(t["whites"], t["mb"]), 2) == t["odds"], t["code"]


def test_overall_odds_match_official_1_in_8_46():
    # Exact overall odds are 1 in 8.4677; Powerball's "1 in 8.46" truncates
    # rather than rounds (every per-tier figure above does round correctly).
    exact = sum(1 / combinatorial_odds(t["whites"], t["mb"]) for t in config.PRIZE_TIERS)
    assert int(100 / exact) / 100 == 8.46


def test_ranges():
    assert (config.WHITE_MIN, config.WHITE_MAX, config.MB_MIN, config.MB_MAX) == (1, 58, 1, 5)
