from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from m4l import scraper
from m4l.scraper import Fetcher, latest_expected_draw_date, plan_dates

ET = ZoneInfo("America/New_York")


class FakeResp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, timeout):
        self.calls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def fetcher(responses, retries=2):
    return Fetcher(session=FakeSession(responses), delay_ms=0, retries=retries, sleep=lambda s: None)


def test_user_agent_is_descriptive():
    f = fetcher([])
    assert "m4l-tracker" in f.session.headers["User-Agent"]


def test_ok_page(page):
    r = fetcher([FakeResp(200, page("zero-2026-08-06"))]).fetch_date("2026-08-06")
    assert r.ok and r.record["date"] == "2026-08-06"


def test_missing_page_404():
    r = fetcher([FakeResp(404, "nope")]).fetch_date("2026-08-06")
    assert not r.ok and r.failure_kind == scraper.MISSING_PAGE


def test_server_errors_retry_then_fail():
    f = fetcher([FakeResp(503), FakeResp(503), FakeResp(503)])
    r = f.fetch_date("2026-08-06")
    assert r.failure_kind == scraper.HTTP_ERROR
    assert len(f.session.calls) == 3  # 1 try + 2 retries


def test_transient_error_then_success(page):
    f = fetcher([requests.ConnectionError("reset"), FakeResp(200, page("zero-2026-08-06"))])
    assert f.fetch_date("2026-08-06").ok


def test_timeout_is_http_error_not_zero():
    r = fetcher([requests.Timeout("slow")] * 3).fetch_date("2026-08-06")
    assert not r.ok and r.record is None and r.failure_kind == scraper.HTTP_ERROR


def test_wrong_date_page_is_flagged_not_recorded(page):
    r = fetcher([FakeResp(200, page("zero-2026-08-06"))]).fetch_date("2026-08-07")
    assert not r.ok and r.failure_kind == "not_published"


def test_latest_expected_draw_date_respects_draw_time_and_dst():
    # 11:15pm ET + 45min grace = midnight; before that, yesterday is latest
    assert latest_expected_draw_date(datetime(2026, 11, 5, 23, 0, tzinfo=ET)) == date(2026, 11, 4)
    assert latest_expected_draw_date(datetime(2026, 11, 6, 0, 5, tzinfo=ET)) == date(2026, 11, 5)
    # 10:00 UTC is 6am EDT in summer, 5am EST in winter: yesterday either way
    utc = ZoneInfo("UTC")
    assert latest_expected_draw_date(datetime(2026, 7, 1, 10, 0, tzinfo=utc)) == date(2026, 6, 30)
    assert latest_expected_draw_date(datetime(2026, 12, 1, 10, 0, tzinfo=utc)) == date(2026, 11, 30)


def test_plan_incremental_only_missing_plus_recent_window():
    collected = {f"2026-02-{d}" for d in range(22, 29)} | {"2026-03-01", "2026-03-02"}
    todo = plan_dates(collected, date(2026, 3, 5), recent_days=2)
    # 03-03 missing, 03-04/03-05 missing (also recent window)
    assert todo == ["2026-03-03", "2026-03-04", "2026-03-05"]
    todo = plan_dates(collected | {"2026-03-03", "2026-03-04", "2026-03-05"}, date(2026, 3, 5), recent_days=2)
    assert todo == ["2026-03-04", "2026-03-05"]  # just the recent refresh window


def test_plan_full_refresh_and_single_date():
    assert len(plan_dates({"2026-02-22"}, date(2026, 3, 1), full_refresh=True)) == 8
    assert plan_dates(set(), date(2026, 3, 1), only_dates=["2026-02-25"]) == ["2026-02-25"]
