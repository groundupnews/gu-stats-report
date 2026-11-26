# GroundUp stats report

A Python CLI that produces a monthly HTML stats report for GroundUp (a South
African news site), to be emailed to all@groundup by a cron job.

## Working style

The owner maintains the GroundUp codebase and wants to **understand every
line**. Work step by step: discuss the approach before writing code for each
new section, keep code simple and well commented, avoid unnecessary
dependencies and abstractions, and explain what you changed and why.

## Usage

```bash
python report.py 202501      # report on January 2025
```

The virtualenv is `env/` (not `.venv/`), e.g. `env/bin/python report.py 202501`.

- The single positional argument is compulsory: year and month as `YYYYMM`.
- The month must have finished; malformed or unfinished months are rejected.
- Each figure is compared with the previous month and the same month a year
  earlier. Year-earlier comparisons are nice-to-have: show "n/a" if Matomo
  has no data rather than failing.

## Settings

All settings (URLs, keys, passwords, site IDs) live in `local_settings.py`,
which is in `.gitignore` and never committed. `local_settings.example.py` is
the committed template; add every new setting there with a dummy value and a
comment. Only `report.py` imports settings; other modules receive values as
arguments so they can be understood and tested on their own.

## Files

- `report.py`: CLI entry point. Parses the argument, loads settings,
  orchestrates data fetching, outputs the report. Currently prints a plain-text
  table; its formatting helpers (`fmt_value`, `fmt_change`) are temporary and
  will move into a Jinja2 template.
- `periods.py`: `Month` dataclass. Parses `YYYYMM`, gives `previous()`,
  `year_earlier()`, `matomo_date`, `has_finished()`. No Matomo knowledge.
- `matomo.py`: minimal Matomo Reporting API client (`Matomo.call`) plus
  `site_summary()`, which returns a dict of headline figures for one site and
  month. Token is sent in the POST body, not the URL. Matomo returns `[]`
  instead of `{}` when there's no data; `_as_dict` handles that. Missing values
  are `None` and render as "n/a".
- `groundup.py`: `articles_published(api_url, month)` fetches
  `<GROUNDUP_API_URL>/articles/<year>/<month>/` (fields: pk, url, published;
  no title, so the report shows the slug, linked to the article). Months and
  times are UTC. Adds `path` (used to match Matomo rows) and `slug`.
- `matomo.py` also has `article_pageviews(matomo, site_id, start, end)`: one
  `Actions.getPageUrls` call (`period=range`, `flat=1`, `filter_limit=-1`),
  keyed by path with query strings stripped and combined; avg time weighted
  by page views. Warns on stderr about rows with no URL (e.g. "Others").
- `requirements.txt`: `requests`, `jinja2`.

## Report sections (plan)

1. **Matomo headline figures** for groundup.org.za: visits, unique visitors,
   page views, unique page views, home page views, avg time on home page.
   Uses `VisitsSummary.get`, `Actions.get`, `Actions.getPageUrl`.
   **Status: done, verified against the real Matomo (Oct 2026).** Home page
   URL matches, avg time on page is returned, monthly unique visitors are on.

2. **Articles published in the month** with more than 1,000 page views: a table
   of page views and avg time on page, via Matomo.
   - The list of articles comes from a **new JSON API endpoint the owner will
     write in the GroundUp codebase**, returning for a given month: pk, title,
     URL, publish date.
   - Article URLs are always `/article/<slug>/` and never change. Ignore
     `/newsbypk/<pk>/` (only used by systems, redirects to the article).
   - The owner doesn't think Matomo splits URLs by query string; if real data
     shows it does, combine them.
   - **Counting window:** views from publication up to the day the report is
     run (the 15th of the following month). That's why the cron runs on the
     15th.
   - **Status: written** (`report.py` `popular_articles`, `print_articles`;
     threshold `ARTICLE_MIN_PAGEVIEWS`). Range is 1st of month to today:
     starting on the 1st equals starting at publication. Tested with the real
     GroundUp API and fake Matomo only. On the first real run check for a
     Matomo "Others" warning: it means archives are truncated
     (`datatable_archiving_maximum_rows_subtable_actions`) and views are
     undercounted.

3. **Republication counts** from https://counter.groundup.org.za/stats/ for
   articles published in the month with more than 1,000 hits.
   - The counter is a Django app the owner controls (originally written with
     Claude). Articles are identified by **pk**
     (`https://groundup.org.za/newsbypk/<pk>/`).
   - Decision: add a **JSON endpoint** to the counter app (protected by a key
     in settings) rather than reading its database directly.
   - Same counting window as section 2. Join to the article list by pk.

4. **Videos**: table of all videos with views per platform and total, read from
   an Excel spreadsheet that is maintained by hand. **Undecided:** how the cron
   job finds the file (a fixed path, the newest file in a folder, or a shared
   sheet/URL) and what layout the sheet has. Discuss with the owner before
   building. Likely uses `openpyxl`.

5. **Puzzles** (puzzles.groundup.org.za, its own Matomo site ID): visits and
   page views, plus the top 30 puzzle pages (`Actions.getPageUrls`, `flat=1`).
   `site_summary()` can be reused without a home page URL.

6. **HTML output**: Jinja2 template (agreed). Must be email-safe: inline CSS,
   simple tables, no JavaScript, no external stylesheets. Changes shown as
   coloured ▲/▼ percentages. Planned flags: `--output FILE`, `--email`, maybe
   `--cache` for development.

7. **Email and cron**: send via SMTP (credentials in `local_settings.py`) to
   all@groundup on the 15th of each month, reporting on the previous month.
   Cron must compute `YYYYMM` itself, e.g.
   `$(date -d "last month" +\%Y\%m)` (escape `%` in crontab) or via a small
   wrapper script. Log output, and **notify on failure**: a report that never
   arrives without anyone noticing is the main risk.

## Where it runs

On the GroundUp server via cron, but it must also run remotely (e.g. on the
owner's laptop). Everything is fetched over HTTP (Matomo API, GroundUp API,
counter API), so only the email settings and the spreadsheet location are
machine-specific.

## Next steps

1. Owner runs `python report.py <YYYYMM>` against the real Matomo; adjust
   section 1 based on the output.
2. Run section 2 against the real Matomo (see its checks above).
3. Then counter endpoint and section 3, puzzles, HTML template, videos, email,
   cron.
