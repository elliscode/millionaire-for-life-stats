# Millionaire for Life Tracker: Deployment Steps

A manual runbook. Every AWS resource is created by hand (console or CLI), in the same style as `foursure`. Replace these placeholders everywhere, including in the JSON files under `deploy/`:

| Placeholder | Meaning |
|---|---|
| `m4l-elliscode-com` | bucket name (rename everywhere if you use a different one) |
| `ACCOUNT_ID` | your AWS account id |
| `DISTRIBUTION_ID` | the CloudFront distribution id (from Part 1, step 3) |
| `us-east-1` | region for the Lambda and the scheduler (any region works; the ACM cert must be in us-east-1 regardless) |

- **Part 1:** one-time setup
- **Part 2:** first publish
- **Part 3:** every later deploy

---

## Part 1: One-time AWS setup

### ☐ 1. S3 bucket

- [ ] Create bucket `m4l-elliscode-com`.
- [ ] **Block all public access** stays ON. CloudFront reads through OAC; nothing is public.
- [ ] No CORS needed: the page never fetches anything cross-origin.

Layout the Lambda maintains (you never upload to `site/` by hand):

```
state/historical-results.json   authoritative dataset (private)
state/scrape-failures.json      failure log (private)
state/corrections.json          changed-after-refresh log (private)
state/pending.json              latest-date pages not populated yet; alarm held until 6 a.m. ET (private)
state/snapshots/*.html          raw Powerball HTML for new/failed dates (private)
state/publish-manifest.json     hash of the last published index.html (private)
site/index.html                 the website (served)
site/assets/*.{css,js}          content-hashed, immutable (served)
site/data/historical-results.json  public copy of the verified data (served)
```

### ☐ 2. ACM certificate

- [ ] In **us-east-1**, request a public cert for `m4l.elliscode.com` with DNS validation (one click in Route53 if the zone is there). Wait for **Issued**.

### ☐ 3. CloudFront distribution

- [ ] Origin domain: the bucket's REST endpoint (`m4l-elliscode-com.s3.us-east-1.amazonaws.com`), **not** the website endpoint.
- [ ] **Origin path: `/site`**. This keeps `state/` unreachable from the web.
- [ ] Origin access: **Origin access control (OAC)**, create a new OAC (sign requests). When CloudFront offers to update the bucket policy, let it, or use the next step.
- [ ] Viewer protocol policy: **Redirect HTTP to HTTPS**.
- [ ] Cache policy: **CachingOptimized**. It honors the `Cache-Control` headers the Lambda sets: 5 min for `index.html` and the data JSON, 1 year for hashed assets.
- [ ] Response headers policy (optional, recommended): **SecurityHeadersPolicy**.
- [ ] Alternate domain name: `m4l.elliscode.com`; custom SSL cert: the one from step 2.
- [ ] Default root object: `index.html`.
- [ ] Note the **distribution id** and fill `DISTRIBUTION_ID` into the `deploy/*.json` files.

### ☐ 4. Bucket policy

- [ ] Replace the bucket policy with `deploy/bucket-policy.json` (placeholders filled). It grants CloudFront `GetObject` on `site/*` **only**. If CloudFront auto-wrote a policy covering `/*`, swap it for this narrower one.

### ☐ 5. DNS

- [ ] Route53 → `elliscode.com` zone → create `m4l` **A (Alias)** → the CloudFront distribution. Optionally add **AAAA (Alias)** too.

### ☐ 6. Lambda execution role

- [ ] Create role `m4l-tracker-role` (trusted entity: Lambda).
- [ ] Attach managed policy **AWSLambdaBasicExecutionRole** (CloudWatch Logs).
- [ ] Add inline policy from `deploy/lambda-role-policy.json`:
  - `s3:ListBucket` on the bucket, so missing keys come back as 404 instead of 403
  - get/put on `state/*` and `site/*`
  - `cloudfront:CreateInvalidation` on this distribution only

### ☐ 7. Lambda function

- [ ] Name **`m4l-tracker`**, runtime **Python 3.14**, architecture **arm64** (must match `release.sh`'s `--platform linux/arm64`), role from step 6.
- [ ] Handler: **`m4l.handler.lambda_handler`**.
- [ ] Timeout: **15 min** (900 s). A normal day takes ~10–20 s (about 7 page fetches). The headroom is for full refreshes.
- [ ] Memory: **512 MB**.
- [ ] Configuration → Asynchronous invocation → **Retry attempts: 0**. The function deliberately fails when Powerball's HTML changes, and retrying won't fix that.
- [ ] Environment variables:

| Variable | Value |
|---|---|
| `BUCKET_NAME` | `m4l-elliscode-com` |
| `CLOUDFRONT_DISTRIBUTION_ID` | from step 3 |

  Optional tuning (defaults shown): `REQUEST_DELAY_MS=750`, `REQUEST_RETRIES=2`, `REQUEST_TIMEOUT_S=20`, `RECENT_WINDOW_DAYS=7`, `MAX_FETCHES_PER_RUN=300`, `RESULTS_GRACE_MINUTES=45`, `STALE_AFTER_DAYS=2`, `USER_AGENT`, `SITE_URL`.

### ☐ 8. Deploy the code once

```bash
# OrbStack/Docker must be running
sh release.sh
```

### ☐ 9. EventBridge Scheduler

- [ ] Create a scheduler execution role with `deploy/scheduler-role-policy.json` (trust `scheduler.amazonaws.com`). The console can create this for you.
- [ ] EventBridge → Scheduler → Create schedule `m4l-tracker-daily`:
  - Recurring, cron **`15 0-6 * * ? *`**, time zone **America/New_York**: hourly from 12:15 to 6:15 a.m. Eastern, starting an hour after the 11:15 p.m. ET drawing. The later runs pick up a results page Powerball populated late. Runs that find nothing new don't republish or invalidate. Scheduler handles DST itself, so don't pin this one to UTC.
  - Flexible time window: Off.
  - Target: Lambda `m4l-tracker`, payload `{}`.
  - Retry policy: **off** (max retries 0).

If that night's winner counts aren't posted yet at 12:15 a.m., the date is logged as `not_published` or `results_incomplete` (never as zero winners) and the later hourly runs (through 6:15 a.m.) try again. If it's still missing after that, the next night's runs pick it up, so the site can occasionally lag a day. If Powerball posts preliminary counts that change later, the runs over the next 7 nights re-check that drawing and the correction is logged to `state/corrections.json`. To fill a gap sooner, invoke manually with `{}` any time.

### ☐ 10. Alarm (recommended)

- [ ] SNS → create Standard topic `m4l-alerts` → add an Email subscription → confirm via the link in the email.
- [ ] CloudWatch → Alarms → metric `AWS/Lambda` → By Function Name → `m4l-tracker` → `Errors`. Statistic Sum, period 1 day, threshold ≥ 1, **missing data: treat as good** (most periods have no runs) → notify `m4l-alerts`.

`Errors` is a built-in metric Lambda records automatically. It counts invocations that ended in failure: an uncaught exception, a timeout, running out of memory, or a startup error. For this function that means:
- **Deliberate:** a page had an **unexpected structure or parse error**, which is the "Powerball changed their HTML" signal. Verified data is still saved and published first. The broken dates are listed in `state/scrape-failures.json`, with raw HTML in `state/snapshots/`.
- **Deliberate (staleness check):** the newest verified drawing is more than `STALE_AFTER_DAYS` (default 2) behind the newest drawing that should exist. One night behind is normal when counts post after the 12:15 a.m. run, so this fires on the third night in a row with no new data. It's the catch-all for HTTP errors (Powerball blocking us or being down), results that never get posted, or anything else that silently stops updates.
- **Anything else that broke the run:** S3/CloudFront permission errors, the generated page failing its pre-publish sanity checks, a timeout, or a code bug. The site keeps serving the last good version.

---

## Part 2: First publish

The repo ships a verified dataset (`data/historical-results.json`, every drawing Feb 22 – Nov 4 2026, collected and checked locally on 2026-11-05). Seed the bucket with it so the first run doesn't need to re-fetch 256 pages:

```bash
aws s3 cp data/historical-results.json s3://m4l-elliscode-com/state/historical-results.json \
  --content-type application/json
```

Then run the Lambda once by hand:

```bash
aws lambda invoke --function-name m4l-tracker \
  --cli-binary-format raw-in-base64-out --payload '{}' \
  --log-type Tail --no-cli-pager \
  --query LogResult --output text out.json | base64 -d; echo; cat out.json; echo
```

This prints the tail of the function's log (including any error and traceback), then the response. Don't send the payload to `/dev/stdout`: the CLI's pager redraws the screen and hides it, leaving only `"FunctionError": "Unhandled"` with no message.

Expected: `"added"` lists any drawings since Nov 4, `"publish": {"published": true, ...}`, and an `"invalidation"` id. Then open https://m4l.elliscode.com.

(Skipping the seed also works: the first run backfills everything from launch, ~256 fetches at 750 ms, about 5–6 min.)

Spot-check:

```bash
aws s3 ls s3://m4l-elliscode-com/site/ --recursive
curl -sI https://m4l.elliscode.com/ | grep -iE "cache-control|content-type"
curl -s -o /dev/null -w "%{http_code}\n" https://m4l.elliscode.com/state/historical-results.json   # expect 403/404
```

---

## Part 3: Every later deploy

### Code, template, CSS, or JS changes

```bash
./dev.sh test                 # unit tests
./dev.sh build && ./dev.sh browser-test   # optional: local site + headless Chrome checks
sh release.sh                 # build zip (Docker) + update-function-code
aws lambda invoke --function-name m4l-tracker \
  --cli-binary-format raw-in-base64-out --payload '{"force_publish": true}' \
  --log-type Tail --no-cli-pager \
  --query LogResult --output text out.json | base64 -d; echo; cat out.json; echo
```

`force_publish` regenerates and re-uploads the site immediately. Otherwise the new templates go out on the next daily run.

### Useful manual invocations

| Payload | Effect |
|---|---|
| `{}` | normal incremental run |
| `{"dates": ["2026-08-06"]}` | re-fetch one drawing (changes are logged to `state/corrections.json`) |
| `{"full_refresh": true}` | re-fetch every drawing since launch (~5–6 min) |
| `{"publish": false}` | scrape + save state only |
| `{"force_publish": true}` | re-upload site even if unchanged |

### If the alarm fires

The email doesn't include the reason, so start with the log:

```bash
aws logs tail /aws/lambda/m4l-tracker --since 1d --no-cli-pager | grep -E "ERROR|ScrapeAlarm"
```

- **"no new verified drawing for N day(s)"** (stale): check `scrape-failures.json` (step 1 below) for the `kind`. `http_error`/`missing_page` means Powerball is down or blocking us. Try `./dev.sh fetch <date>` locally to compare. `not_published` means results really aren't up yet. If that's simply a late-posting stretch, no fix is needed: the next successful run clears it.
- **"results page still not populated by the morning deadline"**: the newest drawing's page has been missing its results elements since an overnight run (logged at WARNING, no alarm) and still was at the 6:15 a.m. ET run. `state/pending.json` has the first-seen time and attempt count. If a manual rerun now parses it, Powerball was just slow. Otherwise treat it as a structure failure below.
- **parse/structure failures:** follow the steps below.

1. `aws s3 cp s3://m4l-elliscode-com/state/scrape-failures.json -` to see which dates and why.
2. Download the matching `state/snapshots/<date>.<kind>.html` and reproduce locally: `./dev.sh parse snapshot.html <date>`.
3. Fix `src/m4l/parser.py`, add the snapshot as a fixture + test, `sh release.sh`, then invoke with `{"dates": [...]}` for the affected dates.

Until then the site keeps serving the last good data; nothing unverified is ever published.
