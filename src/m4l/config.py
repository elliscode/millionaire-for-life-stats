"""Game rules, official odds, and runtime settings.

Everything in the GAME RULES section was transcribed from the official
Powerball pages (verified 2026-11-05):

- https://www.powerball.com/millionaire-for-life  ("How To Play")
    "select five numbers from 1-58 and one Millionaire Ball from 1-5",
    "$5 per play", "Drawings are held nightly at 11:15 p.m. ET".
- https://www.powerball.com/millionaire-for-life-prize-chart  (odds)

The odds are the official published figures (rounded to two decimals by
Powerball). tests/test_config.py independently re-derives each one from
the combinatorics of a 5-of-58 + 1-of-5 game, so a transcription typo
fails the test suite instead of quietly skewing the statistics.
"""

import os
from datetime import date

# --------------------------------------------------------------------------
# GAME RULES (official)
# --------------------------------------------------------------------------

GAME_NAME = "Millionaire for Life"
LAUNCH_DATE = date(2026, 2, 22)
WHITE_MIN, WHITE_MAX, WHITE_COUNT = 1, 58, 5
MB_MIN, MB_MAX = 1, 5
PRICE_PER_PLAY_USD = 5
DRAW_TIME_ET = (23, 15)  # 11:15 p.m. America/New_York, nightly

# The nine prize tiers, best first. `code` is the CSS class Powerball's
# own winners table uses on each row (`m5-mb`, `m5`, ... `m1-mb`), which
# is how the parser identifies the combination for each row.
#
# `odds` = the official "1 in X" figure. `prize` = the official prize
# chart's fixed amount (lower tiers) or the annuity description (top two).
PRIZE_TIERS = [
    {"code": "m5-mb", "whites": 5, "mb": True, "odds": 22_910_580.00,
     "label": "5 + Millionaire Ball", "prize": "$1,000,000 per year for life",
     "cash": "$18 million cash option", "lifetime": "top"},
    {"code": "m5", "whites": 5, "mb": False, "odds": 5_727_645.00,
     "label": "5 white balls", "prize": "$100,000 per year for life",
     "cash": "$2.2 million cash option", "lifetime": "second"},
    {"code": "m4-mb", "whites": 4, "mb": True, "odds": 86_455.02,
     "label": "4 + Millionaire Ball", "prize": "$7,500"},
    {"code": "m4", "whites": 4, "mb": False, "odds": 21_613.75,
     "label": "4 white balls", "prize": "$500"},
    {"code": "m3-mb", "whites": 3, "mb": True, "odds": 1_662.60,
     "label": "3 + Millionaire Ball", "prize": "$250"},
    {"code": "m3", "whites": 3, "mb": False, "odds": 415.65,
     "label": "3 white balls", "prize": "$50"},
    {"code": "m2-mb", "whites": 2, "mb": True, "odds": 97.80,
     "label": "2 + Millionaire Ball", "prize": "$25"},
    {"code": "m2", "whites": 2, "mb": False, "odds": 24.45,
     "label": "2 white balls", "prize": "$8"},
    {"code": "m1-mb", "whites": 1, "mb": True, "odds": 15.65,
     "label": "1 + Millionaire Ball", "prize": "$8"},
]
TIER_CODES = [t["code"] for t in PRIZE_TIERS]
TIER_BY_CODE = {t["code"]: t for t in PRIZE_TIERS}
TOP_CODE, SECOND_CODE = "m5-mb", "m5"

# --------------------------------------------------------------------------
# SOURCES
# --------------------------------------------------------------------------

OFFICIAL_GAME_URL = "https://www.powerball.com/millionaire-for-life"
OFFICIAL_PRIZE_CHART_URL = "https://www.powerball.com/millionaire-for-life-prize-chart"
# `pg=3` was checked and makes no difference to the response (identical
# data with or without it); kept only because it's the URL form Powerball's
# own site links to, so the "official result" links look familiar.
DRAW_RESULT_URL = "https://www.powerball.com/draw-result?gc=millionaire-life&pg=3&date={date}"

SITE_URL = os.environ.get("SITE_URL", "https://m4l.elliscode.com/")

# --------------------------------------------------------------------------
# RUNTIME SETTINGS (env-overridable)
# --------------------------------------------------------------------------

USER_AGENT = os.environ.get(
    "USER_AGENT",
    "m4l-tracker/1.0 (independent statistics site; +https://m4l.elliscode.com)",
)
REQUEST_TIMEOUT_S = float(os.environ.get("REQUEST_TIMEOUT_S", "20"))
REQUEST_DELAY_MS = int(os.environ.get("REQUEST_DELAY_MS", "750"))
REQUEST_RETRIES = int(os.environ.get("REQUEST_RETRIES", "2"))
RECENT_WINDOW_DAYS = int(os.environ.get("RECENT_WINDOW_DAYS", "7"))
# Caps one run's HTTP requests. ~300 covers a from-scratch backfill of the
# whole first year inside the Lambda's 15-minute ceiling at 750ms spacing.
MAX_FETCHES_PER_RUN = int(os.environ.get("MAX_FETCHES_PER_RUN", "300"))
# Results are treated as "should exist by now" this long after 11:15 p.m. ET.
RESULTS_GRACE_MINUTES = int(os.environ.get("RESULTS_GRACE_MINUTES", "45"))
# Fail the run (-> Errors alarm) when the newest verified drawing is more than
# this many days behind the newest drawing that should exist. 1 day behind is
# normal when counts post after the nightly run; >2 means 3 nights in a row
# with no new data (blocked, site down, results not posting, ...).
STALE_AFTER_DAYS = int(os.environ.get("STALE_AFTER_DAYS", "2"))
# A newest-drawing page that's missing its results elements (not populated
# yet) is held as "pending" without alarming until this hour ET on the
# morning after the drawing. The scheduler runs hourly overnight, so the
# first run at/after this hour is the one that alarms if it's still empty.
PENDING_ALARM_HOUR_ET = int(os.environ.get("PENDING_ALARM_HOUR_ET", "6"))
