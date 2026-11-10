"""Render the complete static site from verified records.

Everything a visitor needs (chart series, statistics, every drawing's
winning numbers for the ticket checker) is embedded in index.html as a
JSON <script type="application/json"> block. The page makes no network
requests beyond its own same-origin CSS/JS, and a Content-Security-Policy
with `connect-src 'none'` enforces that in the browser.

Static assets get content-hashed filenames (immutable, cached for a year);
index.html and the public data JSON get a short cache lifetime.
"""

import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path
from string import Template
from zoneinfo import ZoneInfo

from . import config
from . import dataset as ds
from .stats import compute_stats

PKG = Path(__file__).resolve().parent
TEMPLATES = PKG / "templates"
STATIC = PKG / "static"

CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
CACHE_SHORT = "public, max-age=300"
ET = ZoneInfo("America/New_York")

# (source path under static/, published stem, extension, content type)
HASHED_ASSETS = [
    ("css/styles.css", "styles", "css", "text/css; charset=utf-8"),
    # Flip-phone (<=240px) overrides; linked with a media attribute in index.html
    ("css/small.css", "small", "css", "text/css; charset=utf-8"),
    ("js/vendor/chart-4.4.7.umd.min.js", "chart-4.4.7", "js", "text/javascript; charset=utf-8"),
    ("js/checker.js", "checker", "js", "text/javascript; charset=utf-8"),
    ("js/app.js", "app", "js", "text/javascript; charset=utf-8"),
]


class SanityError(Exception):
    pass


def esc(s):
    return html.escape(str(s), quote=True)


def fmt_int(n):
    return f"{n:,}"


def fmt_date(iso, long=False):
    d = datetime.strptime(iso, "%Y-%m-%d")
    return d.strftime("%a, %b %-d, %Y" if long else "%b %-d, %Y")


def fmt_big(n):
    if n >= 1e9:
        return f"{n / 1e9:.2f} billion"
    if n >= 1e6:
        return f"{n / 1e6:.1f} million"
    return fmt_int(round(n))


def fmt_p(p):
    if p >= 0.995:
        return "> 0.99"
    if p < 0.001:
        return "< 0.001"
    return f"{p:.3f}"


def fmt_timestamp(iso):
    if not iso:
        return "never"
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC")).astimezone(ET)
    return dt.strftime("%b %-d, %Y at %-I:%M %p ET")


def _json_for_html(obj):
    # "</" can't appear inside a <script> block; "<\/" is the same JSON string.
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def _rules():
    return {
        "whiteMin": config.WHITE_MIN, "whiteMax": config.WHITE_MAX, "whiteCount": config.WHITE_COUNT,
        "mbMin": config.MB_MIN, "mbMax": config.MB_MAX,
        "tiers": [{"code": t["code"], "whites": t["whites"], "mb": t["mb"], "label": t["label"],
                   "prize": t["prize"] + (f" ({t['cash']})" if t.get("cash") else ""),
                   "lifetime": t.get("lifetime")} for t in config.PRIZE_TIERS],
    }


def _page_data(drawings, stats, data):
    return {
        "launchDate": config.LAUNCH_DATE.isoformat(),
        "lastDate": stats["lastDate"],
        # minutes after midnight ET (may be >= 1440) when a night's results count as due;
        # the checker warns when the newest drawing it has is older than that
        "resultsDueMinET": config.DRAW_TIME_ET[0] * 60 + config.DRAW_TIME_ET[1]
                           + config.RESULTS_GRACE_MINUTES,
        "lastUpdated": data.get("lastUpdated"),
        "rules": _rules(),
        "series": stats["series"],
        "plays": [round(p["plays"]) for p in stats["plays"]["perDrawing"]],
        "lastWin": {k: c["lastWinDate"] for k, c in stats["categories"].items()},
        "drawings": [{"d": d["date"], "w": d["winningNumbers"], "m": d["millionaireBall"],
                      "p": [t["prize"] for t in d["prizeTiers"]], "u": d["sourceUrl"]}
                     for d in drawings],
    }


def _card(key, cat, title, prize, cash):
    last = cat["lastWinDate"]
    if last:
        last_html = (f'<a href="{esc(config.DRAW_RESULT_URL.format(date=last))}">'
                     f'<time datetime="{last}">{fmt_date(last)}</time></a>')
        since = (f'<span class="js-days-since" data-from="{last}">{fmt_int(cat["daysSinceLastWin"])}</span>'
                 f' days since last winner')
    else:
        last_html = "None yet"
        since = "No winner since launch"
    winners = "winner" if cat["totalWinners"] == 1 else "winners"
    return f"""
      <article class="stat-card stat-card--{key}">
        <h3 class="stat-card__title"><span class="swatch swatch--{key}" aria-hidden="true"></span>{esc(title)}</h3>
        <p class="stat-card__prize">{esc(prize)} <span class="muted">· {esc(cash)}</span></p>
        <p class="stat-card__value">{fmt_int(cat["totalWinners"])}<span class="stat-card__unit"> {winners}</span></p>
        <dl class="stat-card__facts">
          <div><dt>Winning drawings</dt><dd>{fmt_int(cat["winningDrawings"])}</dd></div>
          <div><dt>Last winning drawing</dt><dd>{last_html}</dd></div>
          <div><dt>Since then</dt><dd>{since}</dd></div>
        </dl>
      </article>"""


def _drought(key, cat, title):
    lon = cat["longestDrought"]
    longest = (f'{fmt_int(lon["length"])} drawings <span class="muted">({fmt_date(lon["start"])} – '
               f'{fmt_date(lon["end"])})</span>') if lon["length"] else "—"
    if cat["lastWinDate"]:
        days = (f'<span class="js-days-since" data-from="{cat["lastWinDate"]}">'
                f'{fmt_int(cat["daysSinceLastWin"])}</span>')
        caption = f'calendar days since the {fmt_date(cat["lastWinDate"])} drawing'
    else:
        days = (f'<span class="js-days-since" data-from="{config.LAUNCH_DATE.isoformat()}">'
                f'{fmt_int(cat["daysSinceLaunch"])}</span>')
        caption = "calendar days since launch, with no winner yet"
    return f"""
      <article class="counter counter--{key}">
        <h3><span class="swatch swatch--{key}" aria-hidden="true"></span>{esc(title)}</h3>
        <p class="counter__value">{days}</p>
        <p class="counter__caption">{caption}</p>
        <dl class="counter__facts">
          <div><dt>Drawings without a winner (current streak)</dt><dd>{fmt_int(cat["currentDrought"])}</dd></div>
          <div><dt>Longest streak without a winner</dt><dd>{longest}</dd></div>
        </dl>
      </article>"""


def _expected_rows(stats):
    rows = []
    for key, title in (("top", "Top prize"), ("second", "Second prize")):
        e = stats["categories"][key]["expected"]
        ratio = f'{e["ratio"]:.2f}×' if e["ratio"] is not None else "—"
        diff = e["difference"]
        rows.append(f"""
          <tr>
            <th scope="row"><span class="swatch swatch--{key}" aria-hidden="true"></span>{title}</th>
            <td data-label="Official odds">1 in {e["odds"]:,.0f}</td>
            <td data-label="Actual">{fmt_int(e["actualWinners"])}</td>
            <td data-label="Expected">{e["expectedWinners"]:.1f}</td>
            <td data-label="Difference">{"+" if diff >= 0 else "−"}{abs(diff):.1f}</td>
            <td data-label="Actual ÷ expected">{ratio}</td>
            <td data-label="P(this many or fewer)">{fmt_p(e["pAtMost"])}</td>
            <td data-label="P(this many or more)">{fmt_p(e["pAtLeast"])}</td>
          </tr>""")
    return "".join(rows)


def _tier_rows(stats):
    rows = []
    for t in stats["plays"]["perTier"]:
        if t["winners"]:
            est = fmt_big(t["impliedPlays"])
            ci = f'{fmt_big(t["ci95"][0])} – {fmt_big(t["ci95"][1])}'
            ratio = f'{t["ratioToPooled"]:.3f}' if t["ratioToPooled"] else "—"
        else:
            est, ci, ratio = "—", "—", "—"
        pooled = "" if t["pooled"] else ' <span class="muted">(not pooled)</span>'
        rows.append(f"""
          <tr>
            <th scope="row">{esc(t["label"])}{pooled}</th>
            <td data-label="Odds">1 in {t["odds"]:,.2f}</td>
            <td data-label="Winners">{fmt_int(t["winners"])}</td>
            <td data-label="Implied plays">{est}</td>
            <td data-label="95% interval">{ci}</td>
            <td data-label="÷ pooled estimate">{ratio}</td>
          </tr>""")
    return "".join(rows)


_SOURCE_MAP_COMMENT = re.compile(rb"^[ \t]*//[#@] sourceMappingURL=.*$\n?", re.M)


def _hashed(src_rel, stem, ext):
    body = (STATIC / src_rel).read_bytes()
    if ext == "js":
        # Vendored libraries (Chart.js) point at a .map file we don't publish.
        # DevTools would try to fetch it and trip the page's connect-src 'none'
        # CSP. Strip the comment so the console stays clean.
        body = _SOURCE_MAP_COMMENT.sub(b"", body)
    h = hashlib.sha256(body).hexdigest()[:10]
    return f"assets/{stem}.{h}.{ext}", body


def build_site(data, today=None):
    """Return (files, index_html). Each file: key, body, contentType, cacheControl, immutable."""
    drawings = ds.verified_drawings(data)
    if not drawings:
        raise SanityError("no verified drawings; refusing to build an empty site")
    stats = compute_stats(drawings)

    files, asset_urls = [], {}
    for src_rel, stem, ext, ctype in HASHED_ASSETS:
        key, body = _hashed(src_rel, stem, ext)
        asset_urls[stem.split("-")[0]] = key
        files.append({"key": key, "body": body, "contentType": ctype,
                      "cacheControl": CACHE_IMMUTABLE, "immutable": True})

    plays = stats["plays"]
    top, second = stats["categories"]["top"], stats["categories"]["second"]
    missing = stats["missingDates"]
    coverage_note = "" if not missing else (
        f'<p class="notice">{len(missing)} drawing date(s) between launch and '
        f'{fmt_date(stats["lastDate"])} have no verified result yet and are excluded '
        f'from every figure: {", ".join(missing[:10])}{"…" if len(missing) > 10 else ""}</p>')

    subs = {
        "csp": ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "connect-src 'none'; font-src 'none'; base-uri 'none'; form-action 'none'"),
        "site_url": esc(config.SITE_URL),
        "css_url": asset_urls["styles"],
        "small_css_url": asset_urls["small"],
        "chart_url": asset_urls["chart"],
        "checker_url": asset_urls["checker"],
        "app_url": asset_urls["app"],
        "last_updated": esc(fmt_timestamp(data.get("lastUpdated"))),
        "last_updated_iso": esc(data.get("lastUpdated") or ""),
        "last_drawing": fmt_date(stats["lastDate"], long=True),
        "drawings_count": fmt_int(stats["drawingsCount"]),
        "launch_date": fmt_date(config.LAUNCH_DATE.isoformat()),
        "official_url": esc(config.OFFICIAL_GAME_URL),
        "prize_chart_url": esc(config.OFFICIAL_PRIZE_CHART_URL),
        "latest_result_url": esc(drawings[-1]["sourceUrl"]),
        "coverage_note": coverage_note,
        "card_top": _card("top", top, "Top prize", "$1 million per year for life", "$18M cash option"),
        "card_second": _card("second", second, "Second prize", "$100,000 per year for life", "$2.2M cash option"),
        "drought_top": _drought("top", top, "Top prize"),
        "drought_second": _drought("second", second, "Second prize"),
        "expected_rows": _expected_rows(stats),
        "tier_rows": _tier_rows(stats),
        "plays_total": fmt_big(plays["totalPlays"]),
        "plays_ci": f'{fmt_big(plays["totalPlaysCI95"][0])} – {fmt_big(plays["totalPlaysCI95"][1])}',
        "plays_avg": fmt_int(round(plays["avgPlaysPerDrawing"])),
        "sales_total": "$" + fmt_big(plays["estimatedSalesUSD"]),
        "first_date": stats["firstDate"],
        "last_date": stats["lastDate"],
        "page_data": _json_for_html(_page_data(drawings, stats, data)),
        "year": stats["lastDate"][:4],
    }
    template = Template((TEMPLATES / "index.html").read_text(encoding="utf-8"))
    index_html = template.substitute(subs)

    public_data = {"game": data.get("game"), "lastUpdated": data.get("lastUpdated"),
                   "note": "Independently collected from powerball.com. Unofficial.",
                   "drawings": drawings}
    files += [
        {"key": "data/historical-results.json", "body": ds.dump_json(public_data).encode(),
         "contentType": "application/json", "cacheControl": CACHE_SHORT, "immutable": False},
        {"key": "favicon.svg", "body": (STATIC / "assets/favicon.svg").read_bytes(),
         "contentType": "image/svg+xml", "cacheControl": "public, max-age=86400", "immutable": False},
        {"key": "robots.txt", "body": b"User-agent: *\nAllow: /\n",
         "contentType": "text/plain", "cacheControl": "public, max-age=86400", "immutable": False},
        {"key": "index.html", "body": index_html.encode("utf-8"),
         "contentType": "text/html; charset=utf-8", "cacheControl": CACHE_SHORT, "immutable": False},
    ]
    return files, index_html


def sanity_check(index_html, data):
    """Refuse to publish a page that doesn't look complete and consistent."""
    drawings = ds.verified_drawings(data)
    problems = []
    if "${" in index_html:
        problems.append("unsubstituted template placeholder")
    marker = '<script type="application/json" id="m4l-data">'
    start = index_html.find(marker)
    if start < 0:
        problems.append("embedded data block missing")
    else:
        end = index_html.find("</script>", start)
        try:
            embedded = json.loads(index_html[start + len(marker):end])
            if len(embedded["drawings"]) != len(drawings):
                problems.append("embedded drawing count mismatch")
            if embedded["drawings"][-1]["d"] != drawings[-1]["date"]:
                problems.append("embedded latest drawing mismatch")
        except (ValueError, KeyError, IndexError) as e:
            problems.append(f"embedded data unreadable: {e}")
    # The "Every drawing" rows are built in the browser from the embedded data
    # (checked above); the page only needs the button and the empty tbody.
    for needle in ('id="history-load"', 'id="history-body"'):
        if needle not in index_html:
            problems.append(f"history table hook missing: {needle}")
    for needle in ("Check Your Numbers", "Unofficial number checker", 'id="winners-chart"'):
        if needle not in index_html:
            problems.append(f"missing section: {needle}")
    if problems:
        raise SanityError("; ".join(problems))
