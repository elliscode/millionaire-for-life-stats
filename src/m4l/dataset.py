"""The authoritative historical dataset plus its failure and correction logs.

Rules enforced here:
- one record per date, ever (keyed by date; no duplicates)
- only parser-verified records enter the dataset; a failed fetch/parse never
  touches an existing record and is never converted to "zero winners"
- a refreshed record that differs from the stored one replaces it, and the
  before/after pair is appended to the corrections log
"""

import json
import logging

from . import config

log = logging.getLogger(__name__)

DATASET_KEY = "historical-results.json"
FAILURES_KEY = "scrape-failures.json"
CORRECTIONS_KEY = "corrections.json"
PENDING_KEY = "pending.json"
SCHEMA_VERSION = 1

# Failure kinds that mean "something is wrong with our parsing or their
# site" and should fail the Lambda invocation (so it shows up in the Errors
# metric). Everything else is expected/transient.
ALARM_KINDS = {"unexpected_structure", "parse_error"}

# The parser's "results elements absent" detail. On the newest expected
# drawing this usually means Powerball hasn't populated the page yet, not
# that the HTML changed, so it's held as "pending" and only alarms if it's
# still failing at config.PENDING_ALARM_HOUR_ET the next morning.
_PENDABLE_KIND = "unexpected_structure"
_PENDABLE_DETAIL_PREFIX = "missing "

# Fields that don't count as a change when comparing a refetched record.
_VOLATILE = {"scrapedAt", "sourceUrl"}


def empty_dataset():
    return {"game": config.GAME_NAME, "schemaVersion": SCHEMA_VERSION,
            "lastUpdated": None, "drawings": []}


def load_json(store, key, default):
    text = store.read_text(key)
    return json.loads(text) if text else default


def dump_json(obj):
    return json.dumps(obj, indent=1, sort_keys=False) + "\n"


def _comparable(record):
    return {k: v for k, v in record.items() if k not in _VOLATILE}


class MergeSummary:
    def __init__(self):
        self.added, self.corrected, self.unchanged = [], [], []
        self.failures = {}  # date -> kind
        self.deferred = set()  # failing dates held as pending this run (no alarm)
        self.pending = None    # update_pending() result, set by the pipeline

    @property
    def changed(self):
        return bool(self.added or self.corrected)

    @property
    def alarms(self):
        return {d: k for d, k in self.failures.items()
                if k in ALARM_KINDS and d not in self.deferred}

    def as_dict(self):
        return {"added": self.added, "corrected": self.corrected,
                "unchanged": len(self.unchanged), "failures": self.failures}


def merge_results(dataset, failures, corrections, results, now_iso):
    """Apply FetchResults in place. Returns MergeSummary."""
    summary = MergeSummary()
    by_date = {d["date"]: d for d in dataset["drawings"]}
    fail_map = failures.setdefault("failures", {})

    for r in results:
        if r.ok:
            fail_map.pop(r.date, None)
            old = by_date.get(r.date)
            if old is None:
                by_date[r.date] = r.record
                summary.added.append(r.date)
            elif _comparable(old) != _comparable(r.record):
                corrections.append({"date": r.date, "detectedAt": now_iso,
                                    "before": old, "after": r.record})
                by_date[r.date] = r.record
                summary.corrected.append(r.date)
                log.warning("correction detected for %s", r.date)
            else:
                summary.unchanged.append(r.date)
        else:
            prev = fail_map.get(r.date, {})
            fail_map[r.date] = {
                "kind": r.failure_kind, "detail": r.detail, "url": r.url,
                "firstSeen": prev.get("firstSeen", now_iso), "lastSeen": now_iso,
                "attempts": prev.get("attempts", 0) + 1,
                "hasVerifiedRecord": r.date in by_date,
            }
            summary.failures[r.date] = r.failure_kind

    dataset["drawings"] = [by_date[d] for d in sorted(by_date)]
    if summary.changed:
        dataset["lastUpdated"] = now_iso
    return summary


def is_pendable(result, latest_expected_iso):
    """This failure may be deferred (until its deadline) instead of alarming."""
    return (not result.ok and result.date == latest_expected_iso
            and result.failure_kind == _PENDABLE_KIND
            and (result.detail or "").startswith(_PENDABLE_DETAIL_PREFIX))


def update_pending(pending, summary, results, latest_expected_iso, now_iso, alarm_due):
    """Apply this run's results to the pending log (in place).

    `alarm_due(date_iso) -> bool`: True once a pending date may alarm
    (PENDING_ALARM_HOUR_ET on the morning after the drawing).

    - pendable miss before its deadline: add/update the entry and defer its
      alarm (summary.deferred)
    - pendable miss at/after the deadline, or any other alarm-kind failure on
      a pending date: escalate (alarm as normal; the entry stays until the
      date parses)
    - success: clear the entry
    Non-alarm failures (http_error, ...) just update an existing entry.

    Returns {"deferred": [...], "escalated": [...], "cleared": [...]}.
    """
    pmap = pending.setdefault("pending", {})
    info = {"deferred": [], "escalated": [], "cleared": []}
    for r in results:
        if r.ok:
            if pmap.pop(r.date, None) is not None:
                info["cleared"].append(r.date)
            continue
        pendable = is_pendable(r, latest_expected_iso)
        entry = pmap.get(r.date)
        if entry is None and not pendable:
            continue
        if entry is None:
            entry = pmap[r.date] = {"firstSeen": now_iso, "attempts": 0}
        entry.update(kind=r.failure_kind, detail=r.detail, url=r.url, lastSeen=now_iso,
                     attempts=entry.get("attempts", 0) + 1)
        if pendable and not alarm_due(r.date):
            summary.deferred.add(r.date)
            info["deferred"].append(r.date)
        elif r.failure_kind in ALARM_KINDS:
            entry.setdefault("escalatedAt", now_iso)
            info["escalated"].append(r.date)
    return info


def verified_drawings(dataset):
    """The only records anything downstream is allowed to publish."""
    return [d for d in dataset["drawings"] if d.get("verified") is True]
