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

  Optional tuning (defaults shown): `REQUEST_DELAY_MS=750`, `REQUEST_RETRIES=2`, `REQUEST_TIMEOUT_S=20`, `RECENT_WINDOW_DAYS=7`, `MAX_FETCHES_PER_RUN=300`, `RESULTS_GRACE_MINUTES=45`, `USER_AGENT`, `SITE_URL`.

### ☐ 8. Deploy the code once

```bash
# OrbStack/Docker must be running
sh release.sh
```

### ☐ 9. EventBridge Scheduler

- [ ] Create a scheduler execution role with `deploy/scheduler-role-policy.json` (trust `scheduler.amazonaws.com`). The console can create this for you.
- [ ] EventBridge → Scheduler → Create schedule `m4l-tracker-daily`:
  - Recurring, cron **`0 6 * * ? *`**, time zone **America/New_York**: 6:00 a.m. Eastern every day, about 6¾ hours after the 11:15 p.m. ET drawing. Scheduler handles DST itself.
    - If you'd rather pin UTC: `cron(0 10 * * ? *)` with time zone UTC, which is 6 a.m. EDT / 5 a.m. EST. Both are safe.
  - Flexible time window: Off.
  - Target: Lambda `m4l-tracker`, payload `{}`.
  - Retry policy: **off** (max retries 0).

If results aren't posted yet when it runs, that date is logged as `not_published` (not as zero winners) and picked up on the next run.

### ☐ 10. Alarm (recommended)

- [ ] CloudWatch → Alarms → metric `AWS/Lambda` `Errors`, FunctionName `m4l-tracker`, Sum ≥ 1 over 1 day → SNS email to you. The invocation fails only if a page had an **unexpected structure or parse error**, which is the "Powerball changed their HTML" signal. Verified data is still saved and published; the broken dates are listed in `state/scrape-failures.json`, with raw HTML in `state/snapshots/`.

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
  --cli-binary-format raw-in-base64-out --payload '{}' /dev/stdout
```

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
  --cli-binary-format raw-in-base64-out --payload '{"force_publish": true}' /dev/stdout
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

1. `aws s3 cp s3://m4l-elliscode-com/state/scrape-failures.json -` to see which dates and why.
2. Download the matching `state/snapshots/<date>.<kind>.html` and reproduce locally: `./dev.sh parse snapshot.html <date>`.
3. Fix `src/m4l/parser.py`, add the snapshot as a fixture + test, `sh release.sh`, then invoke with `{"dates": [...]}` for the affected dates.

Until then the site keeps serving the last good data; nothing unverified is ever published.
