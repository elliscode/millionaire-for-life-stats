# Project Handoff: Millionaire for Life Tracker

**Project:** Millionaire for Life Tracker  
**Domain:** https://m4l.elliscode.com  
**Developer:** EllisCode  
**Primary goal:** Build an independently maintained historical lottery statistics dashboard with an interactive ticket number checker.

---

# 1. Project Overview

Build a small public-facing website that tracks the historical winning tickets for the two lifetime-prize categories in the Millionaire for Life lottery game.

The website should be an interesting combination of:
- Historical lottery data collection
- Web scraping
- Statistical analysis
- Data visualization
- Interactive ticket checking

The project is primarily for entertainment and statistical curiosity. It may eventually be shared publicly on Reddit and other communities.

The two primary prize categories are:

1. **Top Prize:** $1 million per year for life.
2. **Second Prize:** $100,000 per year for life.

The central feature is a historical graph showing how many winning tickets each prize category has produced over the life of the game.

The secondary feature is an interactive number checker that allows visitors to enter their lottery numbers and compare them against any historical drawing.

The site is an independent project and is not affiliated with Powerball or any state lottery.

# 2. Architecture and Infrastructure

The website should follow the same architecture and general development philosophy as the existing FourSure blog generation workflow.

**Critical requirement: The website must be completely static.**

A visitor opening the website must not trigger:
- API Gateway requests
- Lambda invocations
- Database queries
- External API requests
- Requests to Powerball

All data collection, processing, statistical calculations, and HTML generation happen ahead of time inside a scheduled AWS Lambda.

The Lambda generates the website and uploads the resulting files to S3.

CloudFront serves those static files.

### Architecture

```text
EventBridge Scheduler
        |
        v
Python AWS Lambda
        |
        +-- Scrape Powerball drawing results
        |
        +-- Update historical dataset
        |
        +-- Calculate statistics
        |
        +-- Generate ticket checker data
        |
        +-- Generate static HTML
        |
        v
Amazon S3
        |
        v
CloudFront
        |
        v
m4l.elliscode.com
        |
        v
Visitor's browser
```

No runtime backend is required.

## 3. Technology Stack

### Backend
- Python 3.12 or newer supported Lambda runtime
- AWS Lambda
- EventBridge Scheduler
- Amazon S3
- boto3
- requests
- beautifulsoup4

### Frontend
- HTML5
- CSS3
- Vanilla JavaScript
- Chart.js

Bundle Chart.js locally. Do not depend on external CDNs.

### Hosting
- S3 for static website assets and historical data
- CloudFront for delivery
- Custom domain: `m4l.elliscode.com`

Use existing EllisCode AWS infrastructure and deployment conventions where practical.

Avoid unnecessary infrastructure.

# 4. Official Data Source

Primary source:

https://www.powerball.com/millionaire-for-life

Individual drawing result pages follow this URL pattern:

```text
https://www.powerball.com/draw-result?gc=millionaire-life&pg=3&date=2026-08-06
```

The date parameter identifies the drawing.

Investigate whether `pg=3` is required or whether it can remain fixed.

The game launched February 22, 2026.

Initial historical collection should cover every drawing from February 22, 2026 through the latest available drawing.

**Important discovery:** The general historical results listing does not expose the total winner count for each prize tier. The individual drawing pages do.

Each individual result page contains a prize table with:
- Match combination
- Total winners
- Prize amount

It also contains the winning numbers:
- Five white balls
- One green Millionaire Ball

There are nine prize combinations. Some combinations award the same dollar amount, so preserve the individual combinations separately.

The two lifetime prize categories are the primary focus.

## Data extraction priorities

For every drawing, extract:

- Drawing date
- Five white winning numbers
- Millionaire Ball
- Top prize winner count
- Second prize winner count
- All nine prize combinations, if practical
- Total winners for each combination
- Prize amount
- Original source URL
- Scrape timestamp
- Verification status

Do not assume that a missing result page means zero winners.

Distinguish between:
- Verified zero winners
- Verified winning drawing
- Missing page
- HTTP failure
- Parsing failure
- Unexpected website structure

Never silently convert missing information into zero.

Check Powerball's website terms and access restrictions before implementing automated collection.

# 5. Historical Dataset

Store the historical dataset in S3.

Suggested location:

`s3://BUCKET/data/historical-results.json`

Suggested structure:

```json
{
  "game": "Millionaire for Life",
  "lastUpdated": "2026-11-05T12:00:00Z",
  "drawings": [
    {
      "date": "2026-08-06",
      "winningNumbers": [7, 20, 42, 48, 51],
      "millionaireBall": 3,
      "topPrizeWinners": 0,
      "secondPrizeWinners": 0,
      "prizeTiers": [
        {
          "match": "example combination",
          "totalWinners": 5,
          "prize": "$7,500"
        }
      ],
      "sourceUrl": "https://www.powerball.com/draw-result?gc=millionaire-life&pg=3&date=2026-08-06",
      "scrapedAt": "2026-11-05T12:00:00Z",
      "verified": true
    }
  ]
}
```

The example numbers and prize counts above are illustrative, not verified historical data.

Preserve all drawing dates, including drawings with zero jackpot winners.

The dataset should be the authoritative source for both the statistics dashboard and the ticket checker.

## Data integrity

- Do not create duplicate drawings.
- Preserve original source URLs.
- Preserve the original prize-tier combinations.
- Store raw HTML snapshots when useful for debugging.
- Support refreshing and correcting individual historical drawings.
- Keep track of failed scrapes separately.
- Never publish unverified or incomplete data as verified results.

# 6. Python Scraper Lambda

Implement a Python Lambda responsible for historical data collection and website publishing.

Suggested modules:

```text
src/
├── handler.py
├── scraper.py
├── parser.py
├── statistics.py
├── ticket_checker.py
├── generator.py
└── s3_client.py
```

## Scraper workflow

1. Load historical results from S3.
2. Determine which drawing dates are already collected.
3. Generate a list of missing drawing dates.
4. Fetch the corresponding Powerball result pages.
5. Parse winning numbers and prize-tier counts.
6. Validate the extracted data.
7. Add verified results to the historical dataset.
8. Recalculate statistics.
9. Generate the static website.
10. Upload updated historical data and website files to S3.

## Incremental scraping

The Lambda must be incremental.

It should not download every historical drawing every day.

Instead:
- Fetch missing drawing dates.
- Revisit a small recent window, such as the previous seven days, to catch delayed results or corrections.
- Avoid duplicate records.
- Allow an optional full historical refresh.

Implement:
- HTTP timeouts
- Limited retries
- Modest request delays (approximately 500–1000 ms)
- Low concurrency
- Descriptive User-Agent
- Logging
- HTML snapshots for debugging
- Validation of expected prize categories

If a drawing cannot be retrieved or parsed reliably, retain the existing dataset and flag the failure.

The Lambda must not publish incorrect or incomplete data.

# 7. Historical Jackpot Statistics

This is the primary feature of the website.

Track the two lifetime-prize categories independently.

## A. Daily winners

For every drawing date, record:

- Number of top-prize winning tickets
- Number of second-prize winning tickets

Zero-winner drawings must appear in the dataset.

## B. Cumulative winners

Calculate:

- Total top-prize winners since launch
- Total second-prize winners since launch

These should be calculated from the verified historical drawing records.

## C. Days since last winner

Calculate:
- Drawings since the last top-prize winner
- Drawings since the last second-prize winner
- Calendar days since each most recent winning drawing

Use the actual drawing dates, not assumptions about the number of days between drawings.

## D. Historical droughts

Eventually calculate:
- Longest consecutive drawing streak without a top-prize winner
- Longest consecutive drawing streak without a second-prize winner
- Current streak without a winner for each category

## E. Expected versus actual winners

Use the official published odds for each prize tier.

Do not hardcode odds from an unofficial source.

Expected winners:

`Expected winners = Estimated tickets sold × Probability of winning`

Display:
- Actual winners
- Expected winners
- Difference
- Actual-to-expected ratio
- Probability of observing the actual count or fewer under the expected model

For rare prizes, a Poisson approximation may be appropriate. Explain the assumptions.

## F. Estimated ticket sales

The lower prize combinations may be useful for estimating total ticket sales.

For an individual prize combination:

`Estimated plays = Actual winners / Probability of winning that combination`

Calculate independent estimates from several prize tiers and compare them.

Do not simply add tier-based estimates together.

A more robust combined estimate may be developed using the different prize combinations and their statistical properties.

Clearly label all ticket sales and revenue figures as estimates, not official Powerball sales data.

The earlier discussion produced an unverified estimate of approximately 100 million plays. Do not assume this is correct. Reconstruct the estimates independently using the official odds and scraped results.

# 8. Website Design

Create a clean, modern, responsive dashboard.

The website should feel like a small independent statistics publication.

Avoid excessive animations, unnecessary complexity, or a generic lottery marketing appearance.

## Section 1: Header

Title:

**Millionaire for Life Tracker**

Subtitle:

"Tracking every lifetime-prize winner since the game's launch."

Include:
- Last updated timestamp
- Link to official Powerball results
- Independent-project disclaimer

## Section 2: Lifetime Prize Statistics

Two prominent statistic cards.

**Card 1: Top Prize**
- Total winners
- $1 million per year for life
- Last winning drawing date
- Days since last winner

**Card 2: Second Prize**
- Total winners
- $100,000 per year for life
- Last winning drawing date
- Days since last winner

## Section 3: Historical Winner Graph

This should be the centerpiece of the homepage.

Use Chart.js.

Display two datasets:
- Top-prize winners per drawing
- Second-prize winners per drawing

X-axis: Drawing date.

Y-axis: Number of winning tickets.

Use distinct colors for each prize category.

Provide a toggle between:

1. **Daily winners:** Number of winning tickets on each individual drawing.
2. **Cumulative winners:** Total winners accumulated from launch through each drawing.

Consider making the cumulative graph the default view because it tells the historical story particularly well.

Include useful hover tooltips with drawing dates and winner counts.

## Section 4: Days Since Last Winner

Display separate counters for:
- Top prize
- Second prize

Make clear that these represent days since the most recent verified winning drawing.

## Section 5: Expected vs. Actual

Display the expected and actual jackpot winner counts.

Include a short explanation of the mathematical assumptions.

Avoid suggesting that a drought makes a future win more likely. Each drawing's odds remain independent.

## Section 6: Historical Drawing Table

Display:

| Date | Top Prize Winners | Second Prize Winners |
|---|---:|---:|

Newest drawings first.

Make the table responsive and mobile-friendly.

Each date should link to its official Powerball result page.

# 9. Interactive Feature: Check Your Numbers

This is the second major feature.

Visitors should be able to enter their Millionaire for Life ticket numbers and compare them against any historical drawing.

**This feature must run entirely in client-side JavaScript.**

The generated HTML should contain all historical winning numbers needed for comparison.

No API calls or external requests should occur when someone checks a ticket.

## User interface

Add a section titled:

**Check Your Numbers**

Inputs:
- Drawing date
- Five white ball numbers
- One Millionaire Ball number

The user should be able to:
- Select any drawing date since the game's launch.
- Enter their five white numbers.
- Enter their green Millionaire Ball.
- Submit the numbers for comparison.

Validate:
- Exactly five white numbers.
- White ball numbers are within the official valid range.
- White ball numbers are unique.
- Millionaire Ball is within its official valid range.
- A valid historical drawing exists for the selected date.

Retrieve the valid number ranges from the official game rules. Do not guess or hardcode unverified ranges.

## Comparison logic

Compare the submitted numbers against the selected historical drawing.

Calculate:
- Number of matching white balls.
- Whether the Millionaire Ball matches.
- Matching prize combination.
- Corresponding official prize amount.

Use the official game rules and prize table to determine the matching combination.

Do not simply check whether all six numbers match.

The application should account for every official prize combination.

Display a result such as:

- "No matching prize combination"
- "Matching combination: [combination]"
- "Prize category: [prize amount]"

If the entered numbers match the top or second lifetime prize, make that particularly clear.

## Important limitations and disclaimer

This is an unofficial number comparison tool.

It cannot verify:
- Whether the physical ticket is genuine.
- Whether the ticket was purchased before the drawing.
- Whether the ticket was canceled or otherwise invalidated.
- Whether the ticket is eligible for redemption.
- Whether the ticket has already been claimed.

The site must clearly state:

"Unofficial number checker. This tool compares numbers entered by the user against published historical winning numbers. It does not validate physical lottery tickets or establish eligibility for a prize. Always verify tickets through the official state lottery."

Include a direct link to the official Powerball drawing result.

## Future enhancement: Ticket scanning

Do not implement this initially.

Potential future feature:
- Camera-based ticket scanning.
- OCR to extract ticket numbers.
- Automatically populate the number checker.

For the initial release, manual entry is sufficient.

# 10. Static HTML Generation

The generator should create a complete static website.

Suggested output:

```text
public/
├── index.html
├── css/
│   └── styles.css
├── js/
│   └── chart.min.js
└── assets/
    └── favicon.ico
```

The Lambda should:

1. Calculate all statistics.
2. Embed the historical drawing data directly into the generated HTML.
3. Embed the data required by the ticket checker.
4. Generate the final HTML.
5. Upload the updated files to S3.

Chart.js should consume embedded data.

The ticket checker should consume embedded historical winning numbers.

**Do not fetch a separate JSON file when the visitor loads the page.**

The visitor should only need the HTML and its static assets.

The historical JSON can remain separately available for transparency and future analysis, but it must not be required for the website's interactive features.

# 11. AWS Deployment

Use existing EllisCode AWS conventions.

Required resources:

- Python Lambda
- Lambda execution role
- S3 bucket for historical data and generated website
- EventBridge Scheduler
- CloudFront distribution or existing distribution configuration
- DNS record for `m4l.elliscode.com`

The Lambda requires permission to:
- Read historical data from S3.
- Write updated historical data to S3.
- Write generated website files to S3.

CloudFront should serve the website from S3 using an appropriate origin access configuration.

Avoid making the S3 bucket publicly writable.

## Scheduling

Run once daily after Powerball results should be available.

Use a configurable UTC schedule that accounts for Eastern Time and daylight saving changes.

The scraper should tolerate results not yet being published and retry on the next scheduled execution.

## CloudFront

After successfully publishing a new index.html:
- Invalidate `/index.html` if necessary.
- Give static assets longer cache lifetimes.
- Consider versioned asset filenames when assets change.

Do not invalidate CloudFront unless the website has been successfully regenerated and uploaded.

# 12. Cost and Operational Complexity

Keep the project extremely inexpensive.

Expected workload:
- One Lambda execution daily.
- A small number of HTTP requests.
- Small JSON datasets.
- Static website hosting.
- CloudFront delivery.

No database is needed.

No API Gateway is needed.

No always-running infrastructure is needed.

The website should be entirely static from the visitor's perspective.

# 13. Development and Testing

Build and validate the project locally before deploying to AWS.

Create a local development mode that can:
- Use local historical JSON.
- Generate the website without AWS credentials.
- Run the scraper against a single specified date.
- Run the statistical analysis.
- Test the ticket checker.
- Preview the generated website.

### Scraper tests

Test:
1. A drawing with zero lifetime-prize winners.
2. A drawing with a top-prize winner.
3. A drawing with a second-prize winner.
4. Missing pages.
5. Malformed HTML.
6. Unexpected table structure.
7. Incremental scraping.
8. Repeated execution without duplicate records.
9. Refreshing a historical drawing.

### Ticket checker tests

Test every official prize combination.

Include:
- All white balls matched.
- Four white balls plus Millionaire Ball.
- Three white balls plus Millionaire Ball.
- Various other combinations.
- No matching prize.
- Invalid number ranges.
- Duplicate white numbers.
- Invalid dates.
- Missing historical results.

Use official rules and verified test cases.

### Static-site tests

Verify that:
- The graph works.
- Daily/cumulative toggling works.
- Historical dates can be selected.
- Ticket checking works.
- Mobile layout works.
- No runtime API requests occur.
- No external network requests are required for the core experience.

# 14. Suggested Project Structure

```text
millionaire-for-life/
├── src/
│   ├── handler.py
│   ├── scraper.py
│   ├── parser.py
│   ├── statistics.py
│   ├── ticket_checker.py
│   ├── generator.py
│   └── s3_client.py
├── templates/
│   ├── index.html
│   └── styles.css
├── static/
│   ├── css/
│   ├── js/
│   └── assets/
├── data/
│   └── historical-results.json
├── tests/
│   ├── test_scraper.py
│   ├── test_parser.py
│   ├── test_statistics.py
│   └── test_ticket_checker.py
├── requirements.txt
├── template.yaml
└── README.md
```

Adjust the structure as appropriate for the existing EllisCode deployment conventions.

# 15. Deliverables

Provide:

1. Complete Python Lambda implementation.
2. Historical Powerball results scraper.
3. Initial verified historical dataset from February 22, 2026 through the latest available drawing.
4. Statistical analysis module.
5. Static HTML/CSS/JavaScript website.
6. Daily/cumulative winner graph.
7. Historical drawing table.
8. Interactive historical ticket number checker.
9. S3 persistence.
10. EventBridge scheduling.
11. AWS deployment configuration.
12. README documenting installation, deployment, data sources, and statistical methodology.

Final website:

https://m4l.elliscode.com

# 16. Implementation Priorities

Work in this order:

1. Verify the official Powerball result page structure.
2. Build the scraper and validate historical data.
3. Build the historical dataset.
4. Implement the statistical calculations.
5. Implement the ticket comparison logic using official rules.
6. Build the static website.
7. Test all features locally.
8. Implement AWS deployment.
9. Configure CloudFront and DNS.
10. Enable daily scheduled updates.

Prioritize data accuracy over visual polish.

If the website changes its HTML structure, the Lambda must fail safely and preserve the last known-good published website.

The finished project should be a small, reliable, inexpensive, independently maintained lottery statistics website that updates automatically and provides a useful historical ticket checker.