# Highett Area House Watch

A personal monitor of the house market in four Melbourne suburbs, for an owner who is buying
a house with 3 or 4+ bedrooms. Suburbs in order of preference: Highett, Hampton East,
Cheltenham, Moorabbin. It tracks listed prices and their changes, sale prices, supply, demand,
and macro and local influences. Keep it light on Claude credits: scripts collect the data, and
Claude only interprets it.

## How it runs

- `.github/workflows/watch.yml` runs daily at 20:17 UTC (about 6:17 am AEST / 7:17 am AEDT) and on
  demand. It runs `collect.py`, then `build_dashboard.py`, and commits any changed `data/`, `docs/`
  and `dashboard/artifact.html` as github-actions[bot]. A final step fails the job if any source
  failed, which makes GitHub email the owner. Partial data is still committed.
- Public dashboard: GitHub Pages from `main` `/docs`, at https://jtmam.github.io/Property-Price-Tracker/
- Private dashboard with a weekly written read: Claude artifact
  https://claude.ai/artifact/Ay1vJJzRPFCRPv1HA23gvS. A Claude scheduled task in the Claude app,
  "Weekly house market read" (Mondays 8:53 am Melbourne, id `trig_018EJ4eqDPcCQzF5SxQULnqW`), clones
  this repo, writes `read.md`, runs `python build_dashboard.py --commentary read.md --out-dir /tmp/out`
  and publishes `/tmp/out/dashboard/artifact.html` to that artifact. It never pushes to this repo.
- The daily collection uses no Claude credits.

## Commands (Windows, Python 3.12)

```
python -m pip install -r requirements.txt
python tests/test_pipeline.py      # offline end-to-end test; run before every push
python collect.py                  # live pull from every source (writes data/ and .watch_failed)
python build_dashboard.py          # rebuild docs/index.html and dashboard/artifact.html from data/
```

Local runs of `collect.py` and `build_dashboard.py` rewrite `data/`, `docs/` and
`dashboard/artifact.html`. The bot owns those files: never commit local versions. Restore them
before committing with `git restore data docs dashboard/artifact.html`.

## Git

The bot commits to `main` most mornings. Always `git pull --rebase` before committing, then push.
Keep commits small with plain messages.

## Repo map

- `config.yaml`: suburbs, target property, sources and series specs, and the `watchlist` of local
  influences shown on the dashboard.
- `collect.py`: runs each collector fail-soft, upserts the CSVs, writes `data/_diagnostics.json` and
  `.watch_failed` (gitignored).
- `watch/common.py`: HTTP session (retries, user agent), `upsert()` with change detection,
  diagnostics and the Actions step summary.
- `watch/vgv.py`: Valuer-General Victoria. Finds the workbook links on the statistics page by link
  text, finds the header row by counting period-like cells (handles two-row headers and "No. of
  sales" blocks), then extracts each suburb's medians and sales counts.
- `watch/rba.py`: RBA CSV tables. Picks columns by keyword (`include`, `include_any`, `exclude`,
  matched against Title, Description and Type). `monthly_from_daily` keeps each month's last daily
  value, stamped at month end.
- `watch/abs_sdmx.py`: ABS Data API (SDMX REST, `format=csvfilewithlabels`).
- `build_dashboard.py` and `dashboard/template.html`: injects the data as JSON into one HTML
  template. Writes a full page (`docs/index.html`) and a fragment for the Claude artifact
  (`dashboard/artifact.html`).
- `tests/test_pipeline.py`: fakes each source with fixtures shaped like the real files, runs
  `collect` twice, checks change logging, then builds the dashboard.

## Data files

- `data/sales_medians.csv`: `suburb, freq (Q|A), period (2026-Q1 | 2025), median_price, sales_count`
- `data/macro.csv`: `series, period (month-end ISO date), value`
- `data/changes.csv`: `detected_on, dataset, series, period, old, new, kind`, where kind is `new`,
  `revised`, `revised <column>` or `baseline`
- `data/_diagnostics.json`: status and notes per source (chosen column titles, file URLs, errors)

History is never deleted: sources only show a window, and `upsert()` keeps older rows. The first
rows of a dataset, or of a series added later, are logged as one `baseline` line.

## Conventions to keep

- Collectors fail soft. One bad source or series must not stop the others, and the reason goes in
  diagnostics.
- No build timestamps in outputs, so files change only when data changes and quiet days make no
  commit.
- Choose links and columns by keyword and record what was chosen in diagnostics, so source wording
  changes show up.
- The weekly task depends on the `build_dashboard.py` options (`--data-dir`, `--out-dir`,
  `--commentary`) and on the commentary format (a `date: YYYY-MM-DD` line, then paragraphs and
  `- ` bullet blocks with `[text](url)` links). Keep them compatible, or the task's prompt must be
  updated in the Claude app.
- `dashboard/artifact.html` must stay publishable as a Claude artifact: no doctype, html, head or
  body tags in the fragment; inline CSS and JS; external hosts limited to Google Fonts (and cdnjs if
  a library is ever needed); every colour a CSS token with light and dark values.
- Charts are hand-rolled SVG in the template. Suburb colours follow config order, from a validated
  palette (light `#2a78d6 #eb6834 #1baf7a #eda100`, dark `#3987e5 #d95926 #199e70 #c98500`). One
  y-axis per chart, a legend for two or more series, direct end labels only when they don't collide,
  text in ink tokens rather than series colours, a crosshair tooltip, and data tables as the
  accessible fallback.

## Data caveats

- Valuer-General medians lag about six months (the March 2026 quarter was published in September
  2026), cover all houses with no bedroom split, and swing with small samples: Hampton East had 11
  sales in the March 2026 quarter. Recent quarters get revised as late sales settle.
- Hampton East shares postcode 3188 with Hampton, which is pricier, so avoid postcode-level
  statistics for it.
- RBA table F1.1 is a monthly average, which lags and blends mid-month rate moves. The cash rate
  therefore comes from the daily table F1. The F6 mortgage rate should be the "All institutions"
  series.
- Update 1 renamed two series. The old ids `cash_rate` and `mortgage_rate` stay in `data/macro.csv`
  but are no longer shown. Leave them or prune them deliberately.

## Status (30 September 2026)

- Live since 30 September 2026. The first run was clean: 64 suburb medians and 691 macro rows.
- Update 1 ships with this file: daily cash rate (`cash_rate_target`), all-lender mortgage rate
  (`mortgage_rate_all`), per-series baseline logging, price rounding and footer text. If
  `config.yaml` has no `cash_rate_target`, Update 1 isn't applied yet. After its first run, check
  `data/_diagnostics.json`, confirm the cash rate shows 4.60% for September 2026 (the RBA raised it
  on 29 September), and check that the `cash_rate_target` history goes back to 2015. If the daily
  table starts later, backfill the missing months once from F1.1.

## Backlog, in priority order

1. **Listings feed** (the fast signals): asking prices and every price-guide change, new listings
   per week, stock on market, days on market, and auction results against the guide. Houses only, 3
   and 4+ bedrooms, four suburbs. Victoria's underquoting rules (each Statement of Information gives
   a single price or a range no wider than 10%) make guide changes meaningful.
   - Preferred source: Domain's developer API (developer.domain.com.au), if the owner's project gets
     live data. Store the key as the GitHub Secret `DOMAIN_API_KEY`, and skip cleanly when it's
     missing. Candidate endpoints: residential listings search, suburb performance statistics (by
     suburb, property category and bedrooms), and sales results.
   - Fallback: parse saved-search alert emails from realestate.com.au or Domain, delivered to a
     dedicated Gmail inbox and read over IMAP with an app password stored in GitHub Secrets.
   - Never scrape realestate.com.au or Domain web pages. Their terms prohibit it and they block bots.
   - Suggested files: `data/listings.csv` (current state per listing) and `data/listing_events.csv`
     (listed, guide changed, under offer, sold, withdrawn). Show them in the "Listings, supply and
     demand" panel.
2. **ABS local indicators**: Victorian owner-occupier new loan commitments (dataflow `LEND_HOUSING`)
   and building approvals for the Kingston and Bayside council areas. Find the keys against the live
   API first. Cloud sandboxes may block `data.api.abs.gov.au`, but local runs work.
3. **Optional**: rents (Homes Victoria rental report), and SQM stock on market (check its terms first,
   and mind the postcode caveat).

## Guardrails

- Keep it light: no paid data or APIs without asking the owner, and no LLM calls inside the Action.
- This repo is public. Keep only public market data here. Never commit keys, email addresses or
  personal details; use GitHub Secrets.
- Run `python tests/test_pipeline.py` before every push, and add a fixture case whenever a source
  changes its layout.
