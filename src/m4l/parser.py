"""Parse one Powerball draw-result page into a verified drawing record.

Page structure (verified against live pages, 2026-11-05):

- `#numbers` card: `h5.title-date` ("Thu, Aug 6, 2026"), five
  `.white-balls` divs and one `.millionaire-ball` div.
- `#winners` card: two `.winners-group` rows (Top Prize, Match 5), each with
  a `.winner-location` that reads "None" when nobody won that tier.
- `table.winners-table`: nine body rows. Each row's combination is only
  identifiable by a CSS class on its ball-icon div (`m5-mb`, `m5`, `m4-mb`
  ... `m1-mb`), then `td[data-label="Total Winners"]` and
  `td[data-label="Prize"]`.

IMPORTANT quirk: requesting a date with no published results does NOT 404.
Powerball silently serves the nearest drawing instead (a pre-launch date
returns Feb 22's page, a future or not-yet-posted date returns the latest
one). The displayed date is therefore always compared against the requested
date, and a mismatch is reported, never recorded.

Anything unexpected raises ParseError with a `kind` so the caller can tell
"results not posted yet" apart from "Powerball changed its HTML".
"""

import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from . import config

# ParseError kinds
NOT_PUBLISHED = "not_published"        # page shows an earlier drawing than requested
NO_DRAWING = "no_drawing"              # page shows a later drawing (e.g. pre-launch date)
INCOMPLETE = "results_incomplete"      # right drawing, but winner counts not posted
UNEXPECTED_STRUCTURE = "unexpected_structure"
PARSE_ERROR = "parse_error"


class ParseError(Exception):
    def __init__(self, kind, detail):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


_TIER_CLASS = re.compile(r"^m\d(-mb)?$")


def _text(el):
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def _int(text, what):
    cleaned = text.replace(",", "").strip()
    if not re.fullmatch(r"\d+", cleaned):
        raise ParseError(PARSE_ERROR, f"{what} is not a whole number: {text!r}")
    return int(cleaned)


def _parse_display_date(text, what):
    try:
        return datetime.strptime(text.strip(), "%a, %b %d, %Y").date()
    except ValueError:
        raise ParseError(UNEXPECTED_STRUCTURE, f"{what} date not recognized: {text!r}")


def parse_draw_page(html, requested_date, scraped_at, source_url=None):
    """Return a verified record dict for `requested_date`, or raise ParseError."""
    if isinstance(requested_date, str):
        requested_date = date.fromisoformat(requested_date)
    soup = BeautifulSoup(html, "html.parser")

    numbers = soup.select_one("#numbers")
    winners = soup.select_one("#winners")
    table = soup.select_one("table.winners-table")
    if not numbers or not winners or not table:
        missing = [n for n, el in (("#numbers", numbers), ("#winners", winners),
                                   ("table.winners-table", table)) if not el]
        raise ParseError(UNEXPECTED_STRUCTURE, f"missing {', '.join(missing)}")

    # --- date check (must come before anything is trusted) ---------------
    shown = _parse_display_date(_text(numbers.select_one(".title-date")), "numbers card")
    if shown != requested_date:
        kind = NOT_PUBLISHED if shown < requested_date else NO_DRAWING
        raise ParseError(kind, f"requested {requested_date}, page shows {shown}")
    winners_shown = _parse_display_date(_text(winners.select_one(".title-date")), "winners card")
    if winners_shown != requested_date:
        raise ParseError(UNEXPECTED_STRUCTURE,
                         f"winners card date {winners_shown} != {requested_date}")

    # --- winning numbers ---------------------------------------------------
    whites = [_int(_text(el), "white ball") for el in numbers.select(".white-balls")]
    mbs = [_int(_text(el), "Millionaire Ball") for el in numbers.select(".millionaire-ball")]
    if len(whites) != config.WHITE_COUNT or len(mbs) != 1:
        raise ParseError(UNEXPECTED_STRUCTURE,
                         f"expected 5 white + 1 Millionaire Ball, got {len(whites)} + {len(mbs)}")
    if len(set(whites)) != config.WHITE_COUNT or not all(
            config.WHITE_MIN <= n <= config.WHITE_MAX for n in whites):
        raise ParseError(PARSE_ERROR, f"invalid white balls {whites}")
    mb = mbs[0]
    if not config.MB_MIN <= mb <= config.MB_MAX:
        raise ParseError(PARSE_ERROR, f"invalid Millionaire Ball {mb}")

    # --- prize table -------------------------------------------------------
    rows = table.select("tbody > tr")
    tiers = {}
    for row in rows:
        balls = row.select_one("div.game-balls")
        codes = [c for c in (balls.get("class", []) if balls else []) if _TIER_CLASS.match(c)]
        if len(codes) != 1:
            raise ParseError(UNEXPECTED_STRUCTURE, f"prize row without a tier code: {codes}")
        code = codes[0]
        if code not in config.TIER_BY_CODE:
            raise ParseError(UNEXPECTED_STRUCTURE, f"unknown prize tier {code!r}")
        if code in tiers:
            raise ParseError(UNEXPECTED_STRUCTURE, f"duplicate prize tier {code!r}")
        count_td = row.select_one('td[data-label="Total Winners"]')
        prize_td = row.select_one('td[data-label="Prize"]')
        if not count_td or not prize_td:
            raise ParseError(UNEXPECTED_STRUCTURE, f"tier {code} missing winners/prize cell")
        count_text = _text(count_td)
        if not re.fullmatch(r"[\d,]+", count_text):
            # e.g. blank or "Pending" while results are still being tallied
            raise ParseError(INCOMPLETE, f"tier {code} winners not posted: {count_text!r}")
        tiers[code] = {
            "code": code,
            "match": config.TIER_BY_CODE[code]["label"],
            "totalWinners": _int(count_text, f"tier {code} winners"),
            "prize": _text(prize_td),
        }
    if set(tiers) != set(config.TIER_CODES):
        raise ParseError(UNEXPECTED_STRUCTURE,
                         f"expected tiers {config.TIER_CODES}, got {sorted(tiers)}")

    # --- cross-check against the separate "Winners" card --------------------
    groups = winners.select(".winners-group")
    if len(groups) != 2:
        raise ParseError(UNEXPECTED_STRUCTURE, f"expected 2 winners groups, got {len(groups)}")
    locations = {}
    for group, code, key in ((groups[0], config.TOP_CODE, "top"),
                             (groups[1], config.SECOND_CODE, "second")):
        loc = _text(group.select_one(".winner-location"))
        count = tiers[code]["totalWinners"]
        if (loc.lower() == "none") != (count == 0):
            raise ParseError(UNEXPECTED_STRUCTURE,
                             f"{key} prize: table says {count} winner(s) but card says {loc!r}")
        locations[key] = "" if count == 0 else loc

    return {
        "date": requested_date.isoformat(),
        "winningNumbers": whites,
        "millionaireBall": mb,
        "topPrizeWinners": tiers[config.TOP_CODE]["totalWinners"],
        "secondPrizeWinners": tiers[config.SECOND_CODE]["totalWinners"],
        "winnerLocations": locations,
        "prizeTiers": [tiers[c] for c in config.TIER_CODES],
        "sourceUrl": source_url or config.DRAW_RESULT_URL.format(date=requested_date.isoformat()),
        "scrapedAt": scraped_at,
        "verified": True,
    }
