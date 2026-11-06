"""Statistics over verified drawing records.

(Named stats.py, not statistics.py, so it can't shadow the stdlib module.)

Estimating plays (ticket sales)
-------------------------------
For a drawing with N plays, each play independently lands in tier k with
probability p_k = 1/odds_k, so the tier-k winner count is
Binomial(N, p_k) ~= Poisson(N * p_k).

- A single tier's estimate is N_k = n_k / p_k.
- The maximum-likelihood estimate pooling several tiers' Poisson counts is
      N = (sum of n_k) / (sum of p_k)
  which is NOT the sum of the per-tier estimates; it's a weighted average
  of them, weighted by p_k (so the common tiers, with the smallest relative
  error, dominate). Its Poisson standard error is sqrt(sum n_k) / sum p_k.

Only the seven fixed-prize tiers are pooled. The two lifetime tiers are
excluded so that "expected lifetime winners" isn't estimated from the very
counts it's compared against.

Caveat: players don't pick numbers uniformly (birthdays, patterns, etc.),
so tier counts on a given night are over-dispersed relative to the model.
Per-tier estimates disagreeing by more than their Poisson intervals is a
sign of that, not a bug, and it's why all sales figures are labeled
estimates.
"""

import math
from datetime import date, timedelta

from . import config

LOWER_TIERS = [t for t in config.PRIZE_TIERS if "lifetime" not in t]
CATEGORIES = {"top": ("topPrizeWinners", config.TOP_CODE),
              "second": ("secondPrizeWinners", config.SECOND_CODE)}


def poisson_cdf(k, lam):
    """P(X <= k) for X ~ Poisson(lam)."""
    if k < 0:
        return 0.0
    if lam == 0:
        return 1.0
    return min(1.0, sum(math.exp(i * math.log(lam) - lam - math.lgamma(i + 1)) for i in range(k + 1)))


def _tier_count(drawing, code):
    for t in drawing["prizeTiers"]:
        if t["code"] == code:
            return t["totalWinners"]
    raise KeyError(code)


def _date(s):
    return date.fromisoformat(s)


def _missing_dates(drawings):
    if not drawings:
        return []
    have = {d["date"] for d in drawings}
    out, d, end = [], config.LAUNCH_DATE, _date(drawings[-1]["date"])
    while d <= end:
        if d.isoformat() not in have:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def estimate_plays(drawings):
    lower_p = sum(1 / t["odds"] for t in LOWER_TIERS)
    per_drawing = []
    for d in drawings:
        n = sum(_tier_count(d, t["code"]) for t in LOWER_TIERS)
        per_drawing.append({"date": d["date"], "plays": n / lower_p})

    total_n = sum(_tier_count(d, t["code"]) for d in drawings for t in LOWER_TIERS)
    pooled = total_n / lower_p if drawings else 0.0
    pooled_se = math.sqrt(total_n) / lower_p if drawings else 0.0

    per_tier = []
    for t in config.PRIZE_TIERS:
        n = sum(_tier_count(d, t["code"]) for d in drawings)
        p = 1 / t["odds"]
        est = n / p
        half = 1.96 * math.sqrt(n) / p
        per_tier.append({
            "code": t["code"], "label": t["label"], "odds": t["odds"],
            "pooled": "lifetime" not in t, "winners": n,
            "impliedPlays": est,
            "ci95": [max(0.0, est - half), est + half],
            "ratioToPooled": (est / pooled) if pooled else None,
        })
    return {
        "method": "pooled Poisson MLE over the seven fixed-prize tiers",
        "totalPlays": pooled,
        "totalPlaysSE": pooled_se,
        "totalPlaysCI95": [pooled - 1.96 * pooled_se, pooled + 1.96 * pooled_se],
        "avgPlaysPerDrawing": pooled / len(drawings) if drawings else 0.0,
        "estimatedSalesUSD": pooled * config.PRICE_PER_PLAY_USD,
        "perDrawing": per_drawing,
        "perTier": per_tier,
    }


def _category_stats(drawings, field, code, total_plays, as_of):
    counts = [d[field] for d in drawings]
    total = sum(counts)
    win_idx = [i for i, c in enumerate(counts) if c > 0]
    last_i = win_idx[-1] if win_idx else None

    # droughts: runs of consecutive verified zero-winner drawings
    longest = {"length": 0, "start": None, "end": None}
    run_start = None
    for i, c in enumerate(counts + [1]):  # sentinel closes a trailing run
        if i < len(counts) and c == 0:
            run_start = i if run_start is None else run_start
        elif run_start is not None:
            length = i - run_start
            if length > longest["length"]:
                longest = {"length": length, "start": drawings[run_start]["date"],
                           "end": drawings[i - 1]["date"]}
            run_start = None

    p = 1 / config.TIER_BY_CODE[code]["odds"]
    expected = total_plays * p
    return {
        "totalWinners": total,
        "winningDrawings": len(win_idx),
        "lastWinDate": drawings[last_i]["date"] if last_i is not None else None,
        "lastWinCount": counts[last_i] if last_i is not None else 0,
        "drawingsSinceLastWin": (len(drawings) - 1 - last_i) if last_i is not None else len(drawings),
        "daysSinceLastWin": (as_of - _date(drawings[last_i]["date"])).days if last_i is not None else None,
        "daysSinceLaunch": (as_of - config.LAUNCH_DATE).days,
        "currentDrought": (len(drawings) - 1 - last_i) if last_i is not None else len(drawings),
        "longestDrought": longest,
        "expected": {
            "odds": config.TIER_BY_CODE[code]["odds"],
            "expectedWinners": expected,
            "actualWinners": total,
            "difference": total - expected,
            "ratio": (total / expected) if expected else None,
            "pAtMost": poisson_cdf(total, expected),
            "pAtLeast": 1 - poisson_cdf(total - 1, expected),
        },
    }


def compute_stats(drawings, as_of=None):
    """`drawings` must be verified records sorted by date (dataset order)."""
    drawings = sorted(drawings, key=lambda d: d["date"])
    if not drawings:
        return {"drawingsCount": 0}
    as_of = as_of or _date(drawings[-1]["date"])
    plays = estimate_plays(drawings)

    series = {"dates": [d["date"] for d in drawings]}
    for key, (field, _) in CATEGORIES.items():
        daily = [d[field] for d in drawings]
        cum, running = [], 0
        for c in daily:
            running += c
            cum.append(running)
        series[f"{key}Daily"], series[f"{key}Cumulative"] = daily, cum

    return {
        "drawingsCount": len(drawings),
        "firstDate": drawings[0]["date"],
        "lastDate": drawings[-1]["date"],
        "asOf": as_of.isoformat(),
        "missingDates": _missing_dates(drawings),
        "categories": {k: _category_stats(drawings, f, c, plays["totalPlays"], as_of)
                       for k, (f, c) in CATEGORIES.items()},
        "plays": plays,
        "series": series,
    }
