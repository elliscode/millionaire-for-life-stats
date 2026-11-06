"""AWS Lambda entry point: m4l.handler.lambda_handler

Triggered once a day by EventBridge Scheduler with an empty event. Manual
invocations can pass options:

    {}                                  normal incremental run
    {"full_refresh": true}              re-fetch every drawing since launch
    {"dates": ["2026-08-06"]}           re-fetch specific drawings only
    {"force_publish": true}             re-upload the site even if unchanged
                                        (use after deploying new code/templates)
    {"publish": false}                  scrape + save state, don't touch the site
    {"max_fetches": 50}                 cap this run's HTTP requests

Environment:
    BUCKET_NAME                   required; state/ and site/ prefixes live here
    CLOUDFRONT_DISTRIBUTION_ID    optional; invalidated after a changed publish
    (plus the optional tuning vars in config.py)

The invocation FAILS (raises) if any page hit an unexpected-structure or
parse error, after saving state and publishing whatever verified data it
has, so the Lambda Errors metric/alarm catches Powerball HTML changes.
"""

import json
import logging
import os

from .pipeline import RunOptions, run
from .storage import S3Storage, invalidate_cloudfront

logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger(__name__)


class ScrapeAlarm(RuntimeError):
    pass


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    bucket = os.environ["BUCKET_NAME"]
    dist = os.environ.get("CLOUDFRONT_DISTRIBUTION_ID", "").strip()

    opts = RunOptions(
        full_refresh=bool(event.get("full_refresh")),
        dates=event.get("dates") or None,
        publish=event.get("publish", True) is not False,
        force_publish=bool(event.get("force_publish")),
        max_fetches=event.get("max_fetches"),
    )
    state = S3Storage(bucket, "state/")
    site = S3Storage(bucket, "site/")
    invalidate = (lambda paths: invalidate_cloudfront(dist, paths)) if dist else None

    out = run(state, site, opts, invalidate=invalidate)
    log.info("run result: %s", json.dumps(out, default=str))
    if out["alarms"]:
        raise ScrapeAlarm(f"parse/structure failures (state saved, see state/scrape-failures.json "
                          f"and state/snapshots/): {out['alarms']}")
    return out
