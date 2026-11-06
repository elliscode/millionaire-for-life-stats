import re

import pytest

from m4l import parser
from m4l.parser import ParseError, parse_draw_page


def parse(html, date):
    return parse_draw_page(html, date, "2026-11-05T00:00:00Z")


def test_zero_winner_drawing(page):
    r = parse(page("zero-2026-08-06"), "2026-08-06")
    assert r["winningNumbers"] == [7, 20, 42, 48, 51]
    assert r["millionaireBall"] == 3
    assert (r["topPrizeWinners"], r["secondPrizeWinners"]) == (0, 0)
    assert [t["totalWinners"] for t in r["prizeTiers"]] == [0, 0, 5, 17, 203, 785, 3879, 14704, 26185]
    assert [t["code"] for t in r["prizeTiers"]][0] == "m5-mb"
    assert r["prizeTiers"][2]["prize"] == "$7,500"
    assert r["verified"] is True
    assert r["sourceUrl"].endswith("date=2026-08-06")


def test_top_prize_winner(page):
    r = parse(page("top-2026-04-27"), "2026-04-27")
    assert (r["topPrizeWinners"], r["secondPrizeWinners"]) == (1, 0)
    assert r["winnerLocations"] == {"top": "OH", "second": ""}


def test_second_prize_winner(page):
    r = parse(page("second-2026-05-08"), "2026-05-08")
    assert (r["topPrizeWinners"], r["secondPrizeWinners"]) == (0, 1)
    assert r["winnerLocations"]["second"] == "IA"


def test_both_lifetime_prizes_same_night(page):
    r = parse(page("both-2026-05-21"), "2026-05-21")
    assert (r["topPrizeWinners"], r["secondPrizeWinners"]) == (1, 1)
    assert r["winnerLocations"] == {"top": "NY", "second": "MI"}


def test_powerball_substitutes_nearest_drawing_for_missing_date(page):
    # Requesting 2026-02-20 (pre-launch) returns Feb 22's page with HTTP 200.
    with pytest.raises(ParseError) as e:
        parse(page("served-2026-02-22-for-2026-02-20"), "2026-02-20")
    assert e.value.kind == parser.NO_DRAWING


def test_not_yet_published_when_page_shows_earlier_drawing(page):
    with pytest.raises(ParseError) as e:
        parse(page("zero-2026-08-06"), "2026-08-07")
    assert e.value.kind == parser.NOT_PUBLISHED


@pytest.mark.parametrize("html", ["", "<html><body>Service unavailable</body></html>",
                                  "<html><body><div id='numbers'>", "\x00\xff garbage <<<>>"])
def test_malformed_html(html):
    with pytest.raises(ParseError) as e:
        parse(html, "2026-08-06")
    assert e.value.kind == parser.UNEXPECTED_STRUCTURE


def test_missing_prize_row_is_unexpected_structure(page):
    html = page("zero-2026-08-06")
    rows = re.findall(r"<tr>\s*<td class=\"match-col\".*?</tr>", html, re.S)
    assert len(rows) == 9
    with pytest.raises(ParseError) as e:
        parse(html.replace(rows[-1], ""), "2026-08-06")
    assert e.value.kind == parser.UNEXPECTED_STRUCTURE


def test_unknown_tier_code_is_unexpected_structure(page):
    html = page("zero-2026-08-06").replace("item-millionaire-life m1-mb", "item-millionaire-life m0-mb")
    with pytest.raises(ParseError) as e:
        parse(html, "2026-08-06")
    assert e.value.kind == parser.UNEXPECTED_STRUCTURE


def test_duplicate_tier_is_unexpected_structure(page):
    html = page("zero-2026-08-06").replace("item-millionaire-life m2\"", "item-millionaire-life m1-mb\"")
    with pytest.raises(ParseError) as e:
        parse(html, "2026-08-06")
    assert e.value.kind == parser.UNEXPECTED_STRUCTURE


def test_renamed_table_class_is_unexpected_structure(page):
    html = page("zero-2026-08-06").replace("winners-table", "prize-table")
    with pytest.raises(ParseError) as e:
        parse(html, "2026-08-06")
    assert e.value.kind == parser.UNEXPECTED_STRUCTURE


def test_wrong_ball_count_is_unexpected_structure(page):
    html = page("zero-2026-08-06").replace("col white-balls", "col other-balls", 1)
    with pytest.raises(ParseError) as e:
        parse(html, "2026-08-06")
    assert e.value.kind == parser.UNEXPECTED_STRUCTURE


def test_pending_counts_are_incomplete_not_zero(page):
    html = re.sub(r'(data-label="Total Winners">\s*)0(\s*</td>)', r"\1Pending\2",
                  page("zero-2026-08-06"), count=1)
    with pytest.raises(ParseError) as e:
        parse(html, "2026-08-06")
    assert e.value.kind == parser.INCOMPLETE


def test_winner_card_disagreeing_with_table_is_rejected(page):
    # Table says 1 top-prize winner but the winners card says "None"
    html = re.sub(r'(data-label="Total Winners">\s*)0(\s*</td>)', r"\g<1>1\2",
                  page("zero-2026-08-06"), count=1)
    with pytest.raises(ParseError) as e:
        parse(html, "2026-08-06")
    assert e.value.kind == parser.UNEXPECTED_STRUCTURE


def test_out_of_range_number_is_parse_error(page):
    html = page("zero-2026-08-06").replace("\n51    </div>", "\n59    </div>", 1)
    with pytest.raises(ParseError) as e:
        parse(html, "2026-08-06")
    assert e.value.kind == parser.PARSE_ERROR
