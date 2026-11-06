import math
from datetime import date

import pytest

from conftest import make_record
from m4l import config
from m4l.stats import compute_stats, estimate_plays, poisson_cdf


def drawings(spec):
    """spec: list of (top, second) per consecutive day from launch."""
    out = []
    for i, (t, s) in enumerate(spec):
        d = date.fromordinal(config.LAUNCH_DATE.toordinal() + i).isoformat()
        out.append(make_record(d, top=t, second=s))
    return out


def test_daily_and_cumulative_series_include_zero_drawings():
    s = compute_stats(drawings([(0, 0), (1, 0), (0, 2), (0, 0), (1, 1)]))
    assert s["series"]["topDaily"] == [0, 1, 0, 0, 1]
    assert s["series"]["topCumulative"] == [0, 1, 1, 1, 2]
    assert s["series"]["secondCumulative"] == [0, 0, 2, 2, 3]
    assert s["categories"]["second"]["totalWinners"] == 3
    assert s["categories"]["second"]["winningDrawings"] == 2


def test_since_last_winner_and_droughts():
    spec = [(0, 0)] * 3 + [(1, 0)] + [(0, 0)] * 5 + [(1, 0)] + [(0, 0)] * 2
    s = compute_stats(drawings(spec))
    top = s["categories"]["top"]
    assert top["lastWinDate"] == "2026-03-03"
    assert top["drawingsSinceLastWin"] == 2 == top["currentDrought"]
    assert top["daysSinceLastWin"] == 2  # as of last drawing 2026-03-05
    assert top["longestDrought"] == {"length": 5, "start": "2026-02-26", "end": "2026-03-02"}


def test_days_since_uses_actual_dates_not_drawing_count():
    ds = drawings([(1, 0), (0, 0)])
    s = compute_stats(ds, as_of=date(2026, 3, 10))
    assert s["categories"]["top"]["daysSinceLastWin"] == 16
    assert s["categories"]["top"]["drawingsSinceLastWin"] == 1


def test_never_won_category():
    s = compute_stats(drawings([(0, 0)] * 4))
    c = s["categories"]["second"]
    assert c["lastWinDate"] is None and c["currentDrought"] == 4
    assert c["longestDrought"]["length"] == 4


def test_missing_dates_reported():
    ds = drawings([(0, 0)] * 4)
    del ds[1]
    assert compute_stats(ds)["missingDates"] == ["2026-02-23"]


def test_poisson_cdf():
    assert poisson_cdf(0, 2.0) == pytest.approx(math.exp(-2))
    assert poisson_cdf(2, 2.0) == pytest.approx(math.exp(-2) * (1 + 2 + 2))
    assert poisson_cdf(-1, 1.0) == 0.0
    assert poisson_cdf(100, 3.0) == pytest.approx(1.0)


def test_plays_estimate_recovers_known_N():
    # Exact expected counts for N plays -> estimate must return N
    N = 400_000_000  # large enough that rounding to whole winners is negligible
    lower = [round(N / t["odds"]) for t in config.PRIZE_TIERS[2:]]
    ds = [make_record("2026-02-22", lower=lower)]
    est = estimate_plays(ds)
    assert est["totalPlays"] == pytest.approx(N, rel=0.002)
    for t in est["perTier"][2:]:
        assert t["impliedPlays"] == pytest.approx(N, rel=0.01)
    assert not est["perTier"][0]["pooled"] and est["perTier"][2]["pooled"]


def test_pooled_estimate_is_weighted_not_summed():
    est = estimate_plays([make_record("2026-02-22")])
    per = [t["impliedPlays"] for t in est["perTier"] if t["pooled"]]
    assert min(per) <= est["totalPlays"] <= max(per)


def test_expected_vs_actual():
    N = 1_000_000
    lower = [round(N / t["odds"]) for t in config.PRIZE_TIERS[2:]]
    ds = [make_record("2026-02-22", top=1, lower=lower)]
    e = compute_stats(ds)["categories"]["top"]["expected"]
    assert e["expectedWinners"] == pytest.approx(N / 22_910_580, rel=0.01)
    assert e["actualWinners"] == 1
    assert e["pAtMost"] == pytest.approx(poisson_cdf(1, e["expectedWinners"]))
    assert e["pAtLeast"] == pytest.approx(1 - math.exp(-e["expectedWinners"]))
