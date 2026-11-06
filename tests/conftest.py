import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture
def page():
    def load(name):
        return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")
    return load


def make_record(date, top=0, second=0, whites=(1, 2, 3, 4, 5), mb=1, lower=None):
    """Synthetic verified record. `lower`: counts for the 7 fixed-prize tiers."""
    from m4l import config
    lower = lower or [2, 10, 150, 600, 2500, 10000, 15000]
    counts = [top, second] + list(lower)
    return {
        "date": date, "winningNumbers": list(whites), "millionaireBall": mb,
        "topPrizeWinners": top, "secondPrizeWinners": second,
        "winnerLocations": {"top": "OH" if top else "", "second": "NY" if second else ""},
        "prizeTiers": [{"code": t["code"], "match": t["label"], "totalWinners": n, "prize": t["prize"]}
                       for t, n in zip(config.PRIZE_TIERS, counts)],
        "sourceUrl": config.DRAW_RESULT_URL.format(date=date),
        "scrapedAt": "2026-11-05T00:00:00Z", "verified": True,
    }
