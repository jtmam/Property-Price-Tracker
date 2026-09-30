# Highett Area House Watch

A light, automated monitor of the house market in Highett, Hampton East, Cheltenham and
Moorabbin (houses, 3 and 4+ bedrooms).

A GitHub Action checks the sources every morning, stores anything new as CSV in `data/`,
and rebuilds the dashboard in `docs/`. It runs on GitHub's free tier and uses no Claude
credits. Claude only reads the data when writing the weekly commentary.

## What it tracks today

| Area | Source | Updates |
|---|---|---|
| Sale prices by suburb (quarterly and 10-year annual medians) | Valuer-General Victoria | Quarterly, about 6 months after quarter end |
| Cash rate, new owner-occupier variable rate, inflation, unemployment, housing credit growth | Reserve Bank of Australia tables | Monthly or quarterly |
| Unemployment rate, Victoria | ABS Data API | Monthly |
| Rezoning and infrastructure (Moorabbin Activity Centre, SRL Cheltenham, council planning) | `watchlist` in `config.yaml` | Checked by the weekly commentary |

Coming next: a listings feed (asking prices and guide changes, new listings, days on market,
clearance), from Domain's developer API or saved-search email alerts.

## Set up (about 10 minutes)

1. Create a new **public** repository on GitHub, e.g. `melb-property-watch`. Public keeps the
   dashboard hosting free and lets Claude read the data without a password. The repo holds
   only public market data; any API keys go in encrypted GitHub Secrets.
2. Push these files (the `.github` folder is hidden in Finder/Explorer, so use git rather than
   drag-and-drop):
   ```bash
   cd melb-property-watch
   git init -b main && git add . && git commit -m "Start market watch"
   git remote add origin https://github.com/YOUR-USERNAME/melb-property-watch.git
   git push -u origin main
   ```
3. **Settings → Pages**: Source "Deploy from a branch", branch `main`, folder `/docs`, Save.
   The dashboard will live at `https://YOUR-USERNAME.github.io/melb-property-watch/`.
4. **Actions tab → Market watch → Run workflow.** The first run takes about a minute and
   records the baseline. After that it runs daily on its own.
5. Send Claude the repo link so it can check the first run and switch on the weekly commentary.

## Day to day

- **Nothing to do.** Days with no new releases make no commit.
- **If a source breaks** (a site changes its layout), the run fails and GitHub emails you.
  Partial data is still saved. `data/_diagnostics.json` and the run's summary page say which
  source failed and why.
- **To change suburbs or series**, edit `config.yaml` (the GitHub web editor is fine).

## Files

| Path | What it is |
|---|---|
| `config.yaml` | Suburbs, target property, sources, watchlist |
| `collect.py`, `watch/` | Collectors (one per source) and shared storage helpers |
| `build_dashboard.py`, `dashboard/template.html` | Builds `docs/index.html` (public page) and `dashboard/artifact.html` (private copy with commentary) |
| `data/sales_medians.csv` | Suburb medians: `suburb, freq (Q/A), period, median_price, sales_count` |
| `data/macro.csv` | Rates and economy: `series, period, value` |
| `data/changes.csv` | Every new value and revision, with the date it was first seen |
| `tests/test_pipeline.py` | Offline test with synthetic fixtures: `python tests/test_pipeline.py` |

## Notes

- Valuer-General medians cover all houses (no bedroom split) and are revised as late sales
  settle. Bedroom-level prices come with the listings feed.
- Hampton East shares postcode 3188 with Hampton, so postcode-level statistics skew it;
  this project uses suburb-level data.
- GitHub pauses scheduled workflows in repos with no activity for 60 days. Data commits count
  as activity, but if it is ever paused, re-enable it in the Actions tab.

Data: Valuer-General Victoria (CC BY 4.0), Reserve Bank of Australia, Australian Bureau of
Statistics (CC BY 4.0).
