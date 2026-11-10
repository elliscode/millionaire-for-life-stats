"""Polite HTTP fetching of Powerball draw-result pages, and run planning.

One request at a time (no concurrency), a fixed delay between requests,
short timeouts, a couple of retries on transient errors only, and a
descriptive User-Agent.
"""

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from . import config
from .parser import ParseError, parse_draw_page

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Failure kinds produced here (parser kinds are in parser.py)
MISSING_PAGE = "missing_page"   # HTTP 404/410
HTTP_ERROR = "http_error"       # other status codes, timeouts, connection errors


class FetchResult:
    """Outcome of fetching + parsing one date: exactly one of record/failure."""

    def __init__(self, date, url, record=None, failure_kind=None, detail="", html=None):
        self.date, self.url = date, url
        self.record, self.failure_kind, self.detail, self.html = record, failure_kind, detail, html

    @property
    def ok(self):
        return self.record is not None


def utc_now_iso():
    return datetime.now(tz=ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_expected_draw_date(now=None):
    """Most recent date whose 11:15 p.m. ET drawing (+ grace) has passed."""
    now_et = (now or datetime.now(tz=ET)).astimezone(ET)
    h, m = config.DRAW_TIME_ET
    cutoff = now_et.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(
        minutes=config.RESULTS_GRACE_MINUTES)
    d = now_et.date()
    return d if now_et >= cutoff else d - timedelta(days=1)


def pending_alarm_due(date_iso, now=None):
    """True once it's PENDING_ALARM_HOUR_ET on the morning after `date_iso`'s drawing."""
    now_et = (now or datetime.now(tz=ET)).astimezone(ET)
    d = datetime.fromisoformat(date_iso).date() + timedelta(days=1)
    deadline = datetime(d.year, d.month, d.day, config.PENDING_ALARM_HOUR_ET, tzinfo=ET)
    return now_et >= deadline


def plan_dates(collected, latest, full_refresh=False, recent_days=None, only_dates=None):
    """Dates to fetch this run, oldest first.

    - every date from launch..latest that isn't collected yet
    - plus the last `recent_days` drawings again, to pick up corrections
    - or everything, for a full refresh
    - or exactly `only_dates`, if given (manual single-date refresh)
    """
    if only_dates:
        return sorted(set(only_dates))
    recent_days = config.RECENT_WINDOW_DAYS if recent_days is None else recent_days
    all_dates = []
    d = config.LAUNCH_DATE
    while d <= latest:
        all_dates.append(d.isoformat())
        d += timedelta(days=1)
    if full_refresh:
        return all_dates
    recent_floor = (latest - timedelta(days=recent_days - 1)).isoformat() if recent_days else None
    return [d for d in all_dates
            if d not in collected or (recent_floor and d >= recent_floor)]


class Fetcher:
    def __init__(self, session=None, delay_ms=None, retries=None, timeout=None, sleep=time.sleep):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT,
                                     "Accept": "text/html"})
        self.delay = (config.REQUEST_DELAY_MS if delay_ms is None else delay_ms) / 1000
        self.retries = config.REQUEST_RETRIES if retries is None else retries
        self.timeout = config.REQUEST_TIMEOUT_S if timeout is None else timeout
        self.sleep = sleep
        self._last = None

    def _wait_turn(self):
        if self._last is not None:
            remaining = self.delay - (time.monotonic() - self._last)
            if remaining > 0:
                self.sleep(remaining)
        self._last = time.monotonic()

    def get(self, url):
        """Return (status_code, text) or raise requests.RequestException."""
        attempt = 0
        while True:
            self._wait_turn()
            try:
                resp = self.session.get(url, timeout=self.timeout)
                # Retry only server-side/transient statuses
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                return resp.status_code, resp.text
            except requests.RequestException as e:
                if attempt >= self.retries:
                    raise
                attempt += 1
                backoff = 2 ** attempt
                log.warning("retrying %s after %s (backoff %ss)", url, e, backoff)
                self.sleep(backoff)

    def fetch_date(self, date_str):
        url = config.DRAW_RESULT_URL.format(date=date_str)
        try:
            status, html = self.get(url)
        except requests.RequestException as e:
            return FetchResult(date_str, url, failure_kind=HTTP_ERROR, detail=str(e))
        if status in (404, 410):
            return FetchResult(date_str, url, failure_kind=MISSING_PAGE, detail=f"HTTP {status}", html=html)
        if status != 200:
            return FetchResult(date_str, url, failure_kind=HTTP_ERROR, detail=f"HTTP {status}", html=html)
        try:
            record = parse_draw_page(html, date_str, utc_now_iso(), source_url=url)
        except ParseError as e:
            return FetchResult(date_str, url, failure_kind=e.kind, detail=e.detail, html=html)
        except Exception as e:  # bs4/unexpected: never let one page kill the run
            log.exception("unexpected parser crash for %s", date_str)
            return FetchResult(date_str, url, failure_kind="parse_error", detail=repr(e), html=html)
        return FetchResult(date_str, url, record=record, html=html)
