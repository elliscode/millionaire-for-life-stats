"""One end-to-end run: scrape -> merge -> persist state -> generate -> publish.

Shared by the Lambda handler and the local CLI; only the storage backends
(and whether CloudFront gets invalidated) differ.

Safety properties:
- state (dataset/failures/corrections) is saved before anything is published
- the site is generated only from verified records
- the generated site must pass sanity checks before any upload
- hashed assets upload first, the data JSON next, index.html LAST, so a
  failure midway leaves the previous index.html (and the old assets it
  references, which are never deleted) fully intact
- CloudFront is invalidated only after index.html uploaded successfully,
  and only if its content actually changed
"""

import hashlib
import logging
from datetime import date

from . import dataset as ds
from .scraper import Fetcher, latest_expected_draw_date, plan_dates, utc_now_iso

log = logging.getLogger(__name__)

PUBLISH_MANIFEST_KEY = "publish-manifest.json"


class RunOptions:
    def __init__(self, full_refresh=False, dates=None, scrape=True, publish=True,
                 force_publish=False, max_fetches=None, snapshots=True):
        self.full_refresh = full_refresh
        self.dates = dates
        self.scrape = scrape
        self.publish = publish
        self.force_publish = force_publish
        self.max_fetches = max_fetches
        self.snapshots = snapshots


def scrape(state, opts, fetcher=None, now=None, progress=None):
    from . import config

    data = ds.load_json(state, ds.DATASET_KEY, ds.empty_dataset())
    failures = ds.load_json(state, ds.FAILURES_KEY, {"failures": {}})
    corrections = ds.load_json(state, ds.CORRECTIONS_KEY, [])

    latest = latest_expected_draw_date(now)
    collected = {d["date"] for d in data["drawings"]}
    todo = plan_dates(collected, latest, full_refresh=opts.full_refresh, only_dates=opts.dates)
    cap = opts.max_fetches or config.MAX_FETCHES_PER_RUN
    if len(todo) > cap:
        # Prefer the oldest gaps; whatever's left is picked up next run.
        log.warning("%d dates planned, capping this run at %d", len(todo), cap)
        todo = todo[:cap]
    log.info("latest expected drawing %s; fetching %d date(s)", latest, len(todo))

    fetcher = fetcher or Fetcher()
    results = []
    for i, d in enumerate(todo, 1):
        r = fetcher.fetch_date(d)
        results.append(r)
        if r.ok:
            log.info("[%d/%d] %s ok top=%s second=%s", i, len(todo), d,
                     r.record["topPrizeWinners"], r.record["secondPrizeWinners"])
        else:
            level = logging.ERROR if r.failure_kind in ds.ALARM_KINDS else logging.WARNING
            log.log(level, "[%d/%d] %s FAILED %s: %s", i, len(todo), d, r.failure_kind, r.detail)
        if progress:
            progress(i, len(todo), r)

    now_iso = utc_now_iso()
    summary = ds.merge_results(data, failures, corrections, results, now_iso)
    summary.latest_expected = latest
    data["lastChecked"] = now_iso

    # Snapshots: every failure (for debugging) and every new/changed record.
    if opts.snapshots:
        keep = set(summary.added) | set(summary.corrected) | set(summary.failures)
        for r in results:
            if r.html and r.date in keep:
                suffix = "" if r.ok else f".{r.failure_kind}"
                state.write(f"snapshots/{r.date}{suffix}.html", r.html, "text/html")

    # Persist state BEFORE publishing anything.
    state.write(ds.DATASET_KEY, ds.dump_json(data), "application/json")
    state.write(ds.FAILURES_KEY, ds.dump_json(failures), "application/json")
    if summary.corrected:
        state.write(ds.CORRECTIONS_KEY, ds.dump_json(corrections), "application/json")
    return data, summary


def publish(state, site, data, force=False, invalidate=None, today=None):
    """Generate the site from verified data and upload it if it changed.

    `invalidate`: callable(paths) -> id, or None to skip CloudFront.
    Returns a dict describing what happened.
    """
    from .generator import build_site, sanity_check

    files, index_html = build_site(data, today=today)
    sanity_check(index_html, data)

    index_sha = hashlib.sha256(index_html.encode("utf-8")).hexdigest()
    manifest = ds.load_json(state, PUBLISH_MANIFEST_KEY, {})
    if not force and manifest.get("indexSha256") == index_sha and site.exists("index.html"):
        log.info("site unchanged (%s), nothing to publish", index_sha[:12])
        return {"published": False, "reason": "unchanged"}

    # 1) immutable hashed assets, 2) data JSON etc, 3) index.html last
    ordered = sorted(files, key=lambda f: (f["key"] == "index.html", not f["immutable"]))
    for f in ordered:
        if f["immutable"] and not force and site.exists(f["key"]):
            continue  # content-addressed: same name == same bytes
        site.write(f["key"], f["body"], f["contentType"], f["cacheControl"])
        log.info("uploaded %s", site.describe(f["key"]))

    manifest = {"indexSha256": index_sha, "publishedAt": utc_now_iso(),
                "drawings": len(ds.verified_drawings(data)),
                "files": [f["key"] for f in files]}
    state.write(PUBLISH_MANIFEST_KEY, ds.dump_json(manifest), "application/json")

    result = {"published": True, "indexSha256": index_sha}
    if invalidate:
        result["invalidation"] = invalidate(["/", "/index.html", "/data/historical-results.json"])
    return result


def freshness(data, latest_expected):
    """How far the newest verified drawing lags the newest one that should exist."""
    from . import config

    drawings = ds.verified_drawings(data)
    newest = max((d["date"] for d in drawings), default=None)
    lag = (latest_expected - date.fromisoformat(newest)).days if newest else None
    return {
        "latestExpected": latest_expected.isoformat(),
        "newestVerified": newest,
        "lagDays": lag,
        "staleAfterDays": config.STALE_AFTER_DAYS,
        "stale": lag is None or lag > config.STALE_AFTER_DAYS,
    }


def run(state, site, opts, fetcher=None, invalidate=None, now=None):
    summary = None
    if opts.scrape:
        data, summary = scrape(state, opts, fetcher=fetcher, now=now)
    else:
        data = ds.load_json(state, ds.DATASET_KEY, ds.empty_dataset())
    out = {"scrape": summary.as_dict() if summary else None}
    if summary:
        out["freshness"] = freshness(data, summary.latest_expected)
        if out["freshness"]["stale"]:
            log.error("dataset is stale: %s", out["freshness"])
    if opts.publish:
        out["publish"] = publish(state, site, data, force=opts.force_publish, invalidate=invalidate)
    out["alarms"] = summary.alarms if summary else {}
    return out
