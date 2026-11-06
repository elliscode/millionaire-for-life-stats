import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from conftest import make_record
from m4l import dataset as ds
from m4l import pipeline
from m4l.generator import SanityError
from m4l.pipeline import RunOptions, run
from m4l.scraper import FetchResult
from m4l.storage import LocalStorage

ET = ZoneInfo("America/New_York")
# "now" such that latest expected drawing is 2026-03-01 (launch + 7 days = 8 drawings)
NOW = datetime(2026, 3, 2, 9, 0, tzinfo=ET)
ALL = ["2026-02-22", "2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26",
       "2026-02-27", "2026-02-28", "2026-03-01"]


class FakeFetcher:
    """date -> record | failure-kind string. Records which dates were fetched."""
    def __init__(self, answers):
        self.answers = answers
        self.fetched = []

    def fetch_date(self, d):
        self.fetched.append(d)
        a = self.answers.get(d, "not_published")
        url = f"https://example/{d}"
        if isinstance(a, str):
            return FetchResult(d, url, failure_kind=a, detail="fake", html="<html/>")
        return FetchResult(d, url, record=a, html="<html/>")


@pytest.fixture
def stores(tmp_path):
    return LocalStorage(tmp_path / "state"), LocalStorage(tmp_path / "site")


def dataset_of(state):
    return json.loads(state.read_text(ds.DATASET_KEY))


def records(**over):
    return {d: over.get(d, make_record(d)) for d in ALL}


def test_initial_backfill_then_incremental(stores):
    state, site = stores
    f = FakeFetcher(records())
    run(state, site, RunOptions(), fetcher=f, now=NOW)
    assert f.fetched == ALL
    assert [d["date"] for d in dataset_of(state)["drawings"]] == ALL

    f2 = FakeFetcher(records())
    out = run(state, site, RunOptions(), fetcher=f2, now=NOW)
    assert f2.fetched == ALL[-7:]           # only the recent window is revisited
    assert out["scrape"]["added"] == [] and out["scrape"]["corrected"] == []


def test_repeated_runs_never_duplicate(stores):
    state, site = stores
    for _ in range(3):
        run(state, site, RunOptions(full_refresh=True), fetcher=FakeFetcher(records()), now=NOW)
    dates = [d["date"] for d in dataset_of(state)["drawings"]]
    assert dates == ALL and len(dates) == len(set(dates))


def test_refresh_corrects_a_drawing_and_logs_it(stores):
    state, site = stores
    run(state, site, RunOptions(), fetcher=FakeFetcher(records()), now=NOW)
    fixed = make_record("2026-02-24", second=1)
    out = run(state, site, RunOptions(dates=["2026-02-24"]),
              fetcher=FakeFetcher({"2026-02-24": fixed}), now=NOW)
    assert out["scrape"]["corrected"] == ["2026-02-24"]
    rec = next(d for d in dataset_of(state)["drawings"] if d["date"] == "2026-02-24")
    assert rec["secondPrizeWinners"] == 1
    log = json.loads(state.read_text(ds.CORRECTIONS_KEY))
    assert log[0]["before"]["secondPrizeWinners"] == 0 and log[0]["after"]["secondPrizeWinners"] == 1


def test_failures_never_become_zero_and_never_erase_records(stores):
    state, site = stores
    run(state, site, RunOptions(), fetcher=FakeFetcher(records(**{"2026-02-25": "http_error"})), now=NOW)
    dates = [d["date"] for d in dataset_of(state)["drawings"]]
    assert "2026-02-25" not in dates                       # missing, not zero
    fails = json.loads(state.read_text(ds.FAILURES_KEY))["failures"]
    assert fails["2026-02-25"]["kind"] == "http_error"

    # Next run: an existing record whose refresh hits a structure change is kept
    out = run(state, site, RunOptions(), fetcher=FakeFetcher(records(**{"2026-03-01": "unexpected_structure"})), now=NOW)
    assert "2026-03-01" in [d["date"] for d in dataset_of(state)["drawings"]]
    assert out["alarms"] == {"2026-03-01": "unexpected_structure"}
    fails = json.loads(state.read_text(ds.FAILURES_KEY))["failures"]
    assert "2026-02-25" not in fails                       # recovered
    assert fails["2026-03-01"]["hasVerifiedRecord"] is True


def test_snapshots_saved_for_new_records_and_failures(stores):
    state, site = stores
    run(state, site, RunOptions(), fetcher=FakeFetcher(records(**{"2026-02-25": "parse_error"})), now=NOW)
    assert state.exists("snapshots/2026-02-24.html")
    assert state.exists("snapshots/2026-02-25.parse_error.html")


def test_publish_skips_unchanged_and_invalidates_only_on_change(stores):
    state, site = stores
    calls = []
    inv = lambda paths: calls.append(paths) or "INV1"
    out = run(state, site, RunOptions(), fetcher=FakeFetcher(records()), now=NOW, invalidate=inv)
    assert out["publish"]["published"] and out["publish"]["invalidation"] == "INV1"
    out = run(state, site, RunOptions(), fetcher=FakeFetcher(records()), now=NOW, invalidate=inv)
    assert out["publish"] == {"published": False, "reason": "unchanged"}
    assert len(calls) == 1


def test_index_html_uploaded_last(stores, monkeypatch):
    state, site = stores
    order = []
    real = site.write
    monkeypatch.setattr(site, "write", lambda k, *a, **kw: (order.append(k), real(k, *a, **kw)))
    run(state, site, RunOptions(), fetcher=FakeFetcher(records()), now=NOW)
    assert order[-1] == "index.html"
    assert all(k.startswith("assets/") for k in order[:4])


def test_failed_upload_leaves_previous_site_and_skips_invalidation(stores, monkeypatch):
    state, site = stores
    run(state, site, RunOptions(), fetcher=FakeFetcher(records()), now=NOW)
    before = site.read_text("index.html")

    def boom(key, *a, **kw):
        raise IOError("S3 down")
    monkeypatch.setattr(site, "write", boom)
    calls = []
    new = records(**{"2026-03-01": make_record("2026-03-01", top=1)})
    with pytest.raises(IOError):
        run(state, site, RunOptions(), fetcher=FakeFetcher(new), now=NOW, invalidate=calls.append)
    assert site.read_text("index.html") == before
    assert calls == []
    # state was still saved, so the next run will publish it
    assert dataset_of(state)["drawings"][-1]["topPrizeWinners"] == 1


def test_empty_dataset_refuses_to_publish(stores):
    state, site = stores
    with pytest.raises(SanityError):
        run(state, site, RunOptions(), fetcher=FakeFetcher({}), now=NOW)
    assert not site.exists("index.html")


def test_generated_page_embeds_everything(stores):
    state, site = stores
    run(state, site, RunOptions(), fetcher=FakeFetcher(records()), now=NOW)
    html = site.read_text("index.html")
    assert "connect-src 'none'" in html
    assert "Unofficial number checker. This tool compares numbers entered by the user" in html
    assert "fetch(" not in html and "XMLHttpRequest" not in html
    for key in ("data/historical-results.json", "favicon.svg", "robots.txt"):
        assert site.exists(key)
    # published JS must not point DevTools at .map files (blocked by connect-src 'none')
    import re
    for key in re.findall(r'src="(assets/[^"]+\.js)"', html):
        body = (site.root / key).read_bytes()
        assert b"sourceMappingURL" not in body, key
    assert any(b"Chart.js v4.4.7" in (site.root / k).read_bytes()
               for k in re.findall(r'src="(assets/[^"]+\.js)"', html))  # license header kept
    # no external scripts or styles
    for src in re.findall(r'(?:src|href)="([^"]+\.(?:js|css))"', html):
        assert not src.startswith(("http:", "https:", "//")), src
