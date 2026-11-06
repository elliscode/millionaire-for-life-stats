"""Compare a user's numbers to a historical drawing (reference implementation).

The website runs the identical logic client-side in static/js/checker.js;
tests/fixtures/checker_cases.json is exercised against BOTH implementations
(tests/test_ticket_checker.py and tests/js/checker.test.mjs) so they can't
drift apart.

Tiers come from config.PRIZE_TIERS (official prize chart). A combination
not in that table (e.g. 1 white ball without the Millionaire Ball, or the
Millionaire Ball alone) is "no prize".
"""

from datetime import date

from . import config


def validate(whites, mb):
    errors = []
    if len(whites) != config.WHITE_COUNT:
        errors.append(f"Enter exactly {config.WHITE_COUNT} white ball numbers.")
    if any(not isinstance(n, int) or not config.WHITE_MIN <= n <= config.WHITE_MAX for n in whites):
        errors.append(f"White ball numbers must be whole numbers from {config.WHITE_MIN} to {config.WHITE_MAX}.")
    if len(set(whites)) != len(whites):
        errors.append("White ball numbers must all be different.")
    if not isinstance(mb, int) or not config.MB_MIN <= mb <= config.MB_MAX:
        errors.append(f"The Millionaire Ball must be a whole number from {config.MB_MIN} to {config.MB_MAX}.")
    return errors


def match_tier(whites, mb, draw_whites, draw_mb):
    w = len(set(whites) & set(draw_whites))
    b = mb == draw_mb
    tier = next((t for t in config.PRIZE_TIERS if t["whites"] == w and t["mb"] == b), None)
    return w, b, tier


def check_ticket(drawings, draw_date, whites, mb):
    errors = []
    try:
        date.fromisoformat(draw_date)
    except (TypeError, ValueError):
        errors.append("Choose a valid drawing date.")
    errors += validate(whites, mb)
    drawing = next((d for d in drawings if d["date"] == draw_date), None)
    if not errors and drawing is None:
        errors.append("No verified result is available for that date.")
    if errors:
        return {"ok": False, "errors": errors}

    w, b, tier = match_tier(whites, mb, drawing["winningNumbers"], drawing["millionaireBall"])
    out = {"ok": True, "date": draw_date, "matchedWhites": w, "matchedMillionaireBall": b,
           "matchedNumbers": sorted(set(whites) & set(drawing["winningNumbers"])),
           "sourceUrl": drawing["sourceUrl"], "tier": None}
    if tier:
        listed = next((t["prize"] for t in drawing["prizeTiers"] if t["code"] == tier["code"]), None)
        out["tier"] = {"code": tier["code"], "label": tier["label"],
                       "prize": tier["prize"] if tier.get("lifetime") else (listed or tier["prize"]),
                       "lifetime": tier.get("lifetime")}
    return out
