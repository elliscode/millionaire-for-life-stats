import json

import pytest

from conftest import FIXTURES
from m4l import config
from m4l.ticket_checker import check_ticket

FX = json.loads((FIXTURES / "checker_cases.json").read_text())


def drawing():
    d = FX["drawing"]
    return [{"date": d["date"], "winningNumbers": d["winningNumbers"], "millionaireBall": d["millionaireBall"],
             "sourceUrl": "https://example/x",
             "prizeTiers": [{"code": t["code"], "prize": p} for t, p in zip(config.PRIZE_TIERS, d["prizes"])]}]


@pytest.mark.parametrize("case", FX["cases"], ids=[c["name"] for c in FX["cases"]])
def test_case(case):
    r = check_ticket(drawing(), case.get("date", FX["drawing"]["date"]), case["whites"], case["mb"])
    if "error" in case:
        assert not r["ok"]
        assert any(case["error"] in e for e in r["errors"]), r["errors"]
        return
    assert r["ok"], r
    if case["tier"] is None:
        assert r["tier"] is None
    else:
        assert r["tier"]["code"] == case["tier"]
        assert r["tier"]["lifetime"] == case.get("lifetime")
        if "prize" in case:
            assert r["tier"]["prize"] == case["prize"]


def test_every_official_tier_is_covered_by_fixture():
    assert {c["tier"] for c in FX["cases"] if c.get("tier")} == set(config.TIER_CODES)


def test_lifetime_prize_text():
    r = check_ticket(drawing(), "2026-01-01", [1, 2, 3, 4, 5], 1)
    assert r["tier"]["prize"] == "$1,000,000 per year for life"
