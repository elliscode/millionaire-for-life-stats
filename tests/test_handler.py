import pytest

from conftest import make_record
from m4l import handler
from m4l.storage import LocalStorage
from test_pipeline import ALL, NOW, FakeFetcher


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point the handler at local storage and a fake fetcher instead of AWS/HTTP."""
    monkeypatch.setenv("BUCKET_NAME", "test-bucket")
    monkeypatch.delenv("CLOUDFRONT_DISTRIBUTION_ID", raising=False)
    stores = {"state/": LocalStorage(tmp_path / "state"), "site/": LocalStorage(tmp_path / "site")}
    monkeypatch.setattr(handler, "S3Storage", lambda bucket, prefix: stores[prefix])
    answers = {d: make_record(d) for d in ALL}
    real_run = handler.run
    monkeypatch.setattr(handler, "run", lambda s, si, o, invalidate=None:
                        real_run(s, si, o, fetcher=FakeFetcher(answers), invalidate=invalidate, now=NOW))
    return stores, answers


def test_scheduled_empty_event(wired):
    stores, _ = wired
    out = handler.lambda_handler({}, None)
    assert out["publish"]["published"] is True
    assert stores["site/"].exists("index.html")


def test_publish_false_leaves_site_alone(wired):
    stores, _ = wired
    handler.lambda_handler({"publish": False}, None)
    assert not stores["site/"].exists("index.html")
    assert stores["state/"].exists("historical-results.json")


def test_structure_change_fails_invocation_but_keeps_data(wired):
    stores, answers = wired
    handler.lambda_handler({}, None)
    answers["2026-03-01"] = "unexpected_structure"
    with pytest.raises(handler.ScrapeAlarm):
        handler.lambda_handler({}, None)
    assert '"2026-03-01"' in stores["state/"].read_text("historical-results.json")
