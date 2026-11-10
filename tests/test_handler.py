import pytest

from conftest import make_record
from m4l import handler
from m4l.storage import LocalStorage
from test_pipeline import AFTER_DEADLINE, ALL, BEFORE_DEADLINE, NOT_POPULATED, NOW, FakeFetcher


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point the handler at local storage and a fake fetcher instead of AWS/HTTP."""
    monkeypatch.setenv("BUCKET_NAME", "test-bucket")
    monkeypatch.delenv("CLOUDFRONT_DISTRIBUTION_ID", raising=False)
    stores = {"state/": LocalStorage(tmp_path / "state"), "site/": LocalStorage(tmp_path / "site")}
    monkeypatch.setattr(handler, "S3Storage", lambda bucket, prefix: stores[prefix])
    answers = {d: make_record(d) for d in ALL}
    clock = {"now": NOW}
    real_run = handler.run
    monkeypatch.setattr(handler, "run", lambda s, si, o, invalidate=None:
                        real_run(s, si, o, fetcher=FakeFetcher(answers), invalidate=invalidate,
                                 now=clock["now"]))
    return stores, answers, clock


def test_scheduled_empty_event(wired):
    stores, _, _ = wired
    out = handler.lambda_handler({}, None)
    assert out["publish"]["published"] is True
    assert stores["site/"].exists("index.html")


def test_publish_false_leaves_site_alone(wired):
    stores, _, _ = wired
    handler.lambda_handler({"publish": False}, None)
    assert not stores["site/"].exists("index.html")
    assert stores["state/"].exists("historical-results.json")


def test_structure_change_fails_invocation_but_keeps_data(wired):
    stores, answers, _ = wired
    handler.lambda_handler({}, None)
    answers["2026-03-01"] = "unexpected_structure"
    with pytest.raises(handler.ScrapeAlarm):
        handler.lambda_handler({}, None)
    assert '"2026-03-01"' in stores["state/"].read_text("historical-results.json")


def test_stale_data_fails_invocation_after_publishing(wired):
    stores, answers, _ = wired
    for d in ALL[-3:]:
        answers[d] = "not_published"   # three nights with nothing new
    with pytest.raises(handler.ScrapeAlarm, match="no new verified drawing for 3 day"):
        handler.lambda_handler({}, None)
    assert stores["site/"].exists("index.html")  # still published what it had


def test_one_late_night_is_not_an_error(wired):
    stores, answers, _ = wired
    answers[ALL[-1]] = "not_published"
    out = handler.lambda_handler({}, None)
    assert out["freshness"]["lagDays"] == 1


def test_unpopulated_latest_page_alarms_only_after_6am(wired):
    stores, answers, clock = wired
    answers[ALL[-1]] = NOT_POPULATED
    clock["now"] = BEFORE_DEADLINE
    out = handler.lambda_handler({}, None)           # 12:15 a.m.: no alarm
    assert out["pending"]["deferred"] == [ALL[-1]]
    clock["now"] = AFTER_DEADLINE
    with pytest.raises(handler.ScrapeAlarm, match="not populated by the morning deadline"):
        handler.lambda_handler({}, None)             # 6:15 a.m.
