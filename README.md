# Millionaire for Life Tracker

**https://m4l.elliscode.com**: an independent, fully static statistics site tracking every lifetime-prize winner in the *Millionaire for Life* lottery since its launch on Feb 22, 2026. It includes a historical winner chart, droughts, expected-vs-actual analysis, estimated ticket sales, and an unofficial client-side number checker.

Not affiliated with Powerball, MUSL, or any state lottery.

## How it works

```
EventBridge Scheduler (hourly 12:15-6:15 a.m. America/New_York)
  └─ Lambda m4l-tracker (Python 3.14, arm64)
       1. load state/historical-results.json from S3
       2. fetch missing dates + re-check the last 7 drawings from powerball.com
       3. parse + validate each page; merge only verified records
       4. save state (dataset, failures, corrections, HTML snapshots)
       5. compute statistics, render the whole site, sanity-check it
       6. upload hashed assets → data JSON → index.html (last)
       7. invalidate CloudFront, only if index.html actually changed
S3 site/  ──(OAC, origin path /site)──  CloudFront  ──  m4l.elliscode.com
```

A visitor loads `index.html` plus three same-origin JS files and one CSS file. All data (chart series, stats, and every drawing's winning numbers for the checker) is embedded in the HTML. The "Every drawing" table isn't server-rendered: its rows are built in the browser from that same embedded data when the visitor presses "Load all drawings", which keeps the initial page light for flip phones. The page's Content-Security-Policy sets `connect-src 'none'`, so the browser itself blocks any runtime request. No API Gateway, database, or external CDN is involved. Chart.js 4.4.7 (MIT) is vendored under `src/m4l/static/js/vendor/`.

## Repo layout

| Path | What it is |
|---|---|
| `src/m4l/config.py` | Official game rules, prize tiers and odds, runtime settings |
| `src/m4l/scraper.py` | Polite fetching (1 request at a time, 750 ms spacing, timeouts, limited retries) and run planning |
| `src/m4l/parser.py` | Powerball draw-result HTML → verified record, or a typed `ParseError` |
| `src/m4l/dataset.py` | Merge rules: no duplicates, failures never become zeros, corrections logged |
| `src/m4l/stats.py` | Winners, cumulative, droughts, plays estimate, expected vs. actual |
| `src/m4l/ticket_checker.py` | Reference implementation of the number checker |
| `src/m4l/generator.py` | Renders the site; sanity checks before publish |
| `src/m4l/pipeline.py` | Orchestrates one run (shared by Lambda and CLI) |
| `src/m4l/storage.py` | S3 and local-directory backends, CloudFront invalidation |
| `src/m4l/handler.py` | Lambda entry point |
| `src/m4l/cli.py` | Local development commands |
| `src/m4l/templates/index.html` | Page template (`string.Template`) |
| `src/m4l/static/css/small.css` | Flip-phone layout, loaded only at ≤240px (KaiOS), plus the bottom-center "Check your numbers" button |
| `src/m4l/static/` | CSS, `app.js` (chart/UI), `checker.js` (checker logic, shared with Node tests), Chart.js, favicon |
| `data/historical-results.json` | Verified seed dataset (Feb 22 – Nov 4, 2026, 256 drawings) |
| `tests/` | pytest suite, Node checker tests, headless-Chrome smoke test, real-page HTML fixtures |
| `deploy/` | IAM, bucket, and scheduler policy JSON |
| `DEPLOYMENT_STEPS.md` | AWS setup checklist and deploy runbook |

## Local development

No AWS credentials are needed for any of this.

```bash
./dev.sh setup                         # .venv with runtime + dev deps (uses uv)
./dev.sh test                          # pytest + Node checker tests
./dev.sh fetch 2026-08-06              # fetch + parse one drawing, print it, save nothing
./dev.sh scrape                        # incremental scrape into ./data, rebuild ./public
./dev.sh scrape --date 2026-08-06      # refresh one drawing
./dev.sh scrape --full                 # re-fetch everything since launch
./dev.sh build                         # rebuild ./public from ./data (no network)
./dev.sh stats                         # statistics as JSON
./dev.sh check 2026-08-06 7 20 42 48 51 3
./dev.sh serve                         # http://localhost:8000
./dev.sh browser-test                  # headless Chrome: chart, toggle, checker, mobile, zero external requests
```

Locally, `./data` plays the role of `s3://BUCKET/state/` and `./public` plays `s3://BUCKET/site/`.

## Data source and collection

- Pages: `https://www.powerball.com/draw-result?gc=millionaire-life&pg=3&date=YYYY-MM-DD`. The `pg` parameter makes no difference to the response.
- Powerball's general results listing lacks per-tier winner counts. The per-date pages have them: winning numbers, a nine-row prize table with total winners and prize per combination, and a separate "Winners" card listing the states of lifetime-prize winners.
- **Quirk handled:** a date with no published results does *not* 404. Powerball silently serves the nearest drawing instead. The parser compares the page's displayed date to the requested date and records a `not_published`/`no_drawing` failure on any mismatch.
- Each record is validated: 5 unique white balls within 1–58, a Millionaire Ball within 1–5, exactly the nine expected tier codes (read from Powerball's own `m5-mb`…`m1-mb` CSS classes), integer counts, and agreement between the prize table and the Winners card.
- Failure kinds: `missing_page`, `http_error`, `not_published`, `no_drawing`, `results_incomplete`, `unexpected_structure`, `parse_error`. None are ever converted to zero. The last two fail the Lambda invocation so an alarm can catch HTML changes. One exception: when the newest expected drawing's page is missing its results elements (`#numbers`, `#winners`, `table.winners-table`), the page usually just isn't populated yet. It goes into `state/pending.json` and logs at WARNING without alarming until `PENDING_ALARM_HOUR_ET` (default 6 a.m. ET) the morning after the drawing. The scheduler runs hourly overnight, so the 6:15 a.m. run alarms as normal if the page is still empty. The entry clears once the date parses.
- **Staleness check:** every run also fails if the newest verified drawing is more than `STALE_AFTER_DAYS` (default 2) behind the newest drawing that should exist. That's the catch-all for being blocked, Powerball being down, or results never posting, which otherwise only show up as logged failures. State is saved and verified data published before the run fails.
- robots.txt (checked 2026-11-05) permits all crawling. The terms of use contain no automated-access clause, but do contain a general intellectual-property clause. This project republishes only factual results (numbers and counts) with links back to each official page. It never republishes Powerball's HTML, text, logos, or styling. Raw HTML snapshots stay in the private `state/` prefix for debugging only.

## Statistical methodology

**Rules and odds** come from the official game page and prize chart. 5 of 1–58 plus 1 of 1–5 gives 22,910,580 combinations. `tests/test_config.py` re-derives every published tier's odds from combinatorics.

**Winners, cumulative totals, droughts** are computed directly from verified records. "Days since" uses actual calendar dates. The page recomputes it in the visitor's browser against today's date (ET) so it doesn't go stale between builds. Any date without a verified record is excluded and called out on the page.

**Estimated plays.** For N plays, the tier-k winner count is ≈ Poisson(N·p_k). Each drawing's N is estimated from the seven fixed-prize tiers pooled: N̂ = Σn_k / Σp_k. That's the maximum-likelihood estimate, a p-weighted average of the per-tier estimates, not their sum. The two lifetime tiers are excluded so they don't predict themselves. The page also shows each tier's standalone estimate.

**Expected vs. actual.** Expected = N̂ × official probability. The page shows the Poisson probability of the observed count or fewer, and or more.

**Caveats, stated on the page.** Number selection isn't uniform, so counts are over-dispersed. The mean is unbiased, but the Poisson p-values and intervals overstate certainty. All sales figures are labeled estimates, never official data. Each drawing is independent; the page says explicitly that a drought doesn't make a win "due".

As of the Nov 4, 2026 drawing, from the seed data:

| | Value |
|---|---|
| Estimated plays | ≈ 100.5 million (≈ 392K per drawing, ≈ $502M at $5) |
| Top prize | 3 winners vs. 4.4 expected (P(≤3) ≈ 0.36) |
| Second prize | 8 winners vs. 17.5 expected (P(≤8) ≈ 0.009 under the Poisson model) |

## Deployment

See **[DEPLOYMENT_STEPS.md](DEPLOYMENT_STEPS.md)**. In short: create the bucket, cert, CloudFront (OAC, origin path `/site`), DNS, role, Lambda, and scheduler once; then `sh release.sh` for each code change.
