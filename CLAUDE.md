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
python report.py 202501                  # writes report-202501.html
python report.py 202501 --output x.html  # writes x.html
```

The virtualenv is `env/` (not `.venv/`), e.g. `env/bin/python report.py 202501`.

- The single positional argument is compulsory: year and month as `YYYYMM`.
- `--warnothers`: print warnings (stderr) for Matomo rows with no URL, e.g.
  "Others". Off by default because the owner has accepted the undercount.
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

- `report.py`: CLI entry point. `build_report(month, warn_others)` returns
  the HTML (used by the CLI `main()` and by `web.py`). Loads settings, fetches
  all data, prepares it (`popular_articles`, `republished_articles`,
  `top_pages`) and renders `templates/report.html` (`render_report`). Jinja2
  filters: `number`, `duration`, `pct_change` (returns a float; the template
  decides arrow and colour). No plain-text output any more.
- `templates/report.html`: the email-safe HTML template (see section 6).
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
- `matomo.py` also has `pageviews_by_path(matomo, site_id, period, date,
  path_prefix=None)`: one `Actions.getPageUrls` call (`flat=1`,
  `filter_limit=-1`), keyed by path with query strings stripped and combined;
  avg time weighted by page views. Skips rows with no URL (e.g. "Others"),
  warning on stderr only if `warn_others=True` (`--warnothers`). Used by
  section 2 (`range`, prefix `/article/`) and section 5 (`month`, no prefix).
- `counter.py`: `republication_hits(...)`, see section 3.
- `videos.py`: `fetch_sheet`, `month_videos`, `videos_summary`, see section 4.
- `web.py`: Flask web interface (see "Web interface" below).
- `templates/form.html`: the web form (ordinary CSS; not part of the email).
- `requirements.txt`: `requests`, `jinja2`, `flask`, `gunicorn`.

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
   - **Status: done, verified against the real Matomo (Oct 2026)**
     (`report.py` `popular_articles`, `print_articles`; threshold
     `ARTICLE_MIN_PAGEVIEWS`). Range is 1st of month to today: starting on
     the 1st equals starting at publication. Matomo's archives are truncated
     ("Others" warnings, ~265k article views in Oct 2026), so figures are
     minimums, softest near the threshold. Owner has accepted this.

2b. **Most viewed Q&As** (`/qanda/<number>/` on groundup.org.za), shown
   under the articles table. Q&As are evergreen, so this is the top
   `TOP_QANDA_PAGES` (20) Q&As by views in the **calendar month**, whenever
   published; not "published in the month". Matomo only, one
   `pageviews_by_path(..., path_prefix="/qanda/")` call; `QANDA_PATH` keeps
   single Q&As and drops the `/qanda/` index (topic `?topic=` versions combine
   into it), `/qanda/rss/` etc. No titles (URLs have none; the articles API
   doesn't cover Q&As): shows the linked path. Owner may later add a titles
   endpoint. Columns: views, unique views, avg time (template macro
   `pages_table`, shared with puzzles).
   - **Status: written, tested with fake Matomo only.**

3. **Republication counts** from https://counter.groundup.org.za/stats/ for
   articles published in the month with more than 1,000 **republication**
   hits (`REPUBLISHED_MIN_HITS`). An independent report and a separate table
   (article, published, sites, hits, top sites): it does not depend on
   Matomo views. "Top sites" lists up to three sites with the most hits,
   e.g. `news24.com (950), iol.co.za (600)`, but only sites with more than
   `TOP_SITE_MIN_HITS` (500) hits; it can be empty.
   - The counter is a Flask app the owner controls (repo
     `groundupnews/counter`, originally written with Claude). Articles are
     identified by **pk** (`https://groundup.org.za/newsbypk/<pk>/`).
   - Decision: no counter changes. `counter.py` here uses the counter's
     existing **CSV export** (`/stats/YYYYMMDD/YYYYMMDD?format=csv&exclude=…`)
     behind nginx basic auth (`COUNTER_USERNAME`/`COUNTER_PASSWORD`).
     GroundUp's own domains are excluded, as in the counter's form. Hits
     summed per pk; "sites" = distinct referrers.
   - Same counting window as section 2. Join to the article list by pk.
   - **Status: done, verified against the real counter.**

4. **Videos**, from a hand-maintained Google Sheet (`videos.py`,
   `report.video_section`). Placed after republication.
   - **One sheet per year**, links in setting `VIDEO_SHEETS = {year: link}`
     (the browser link incl. `gid=` of the tab). Sheets must be shared
     "Anyone with the link can view"; downloaded as CSV from
     `/spreadsheets/d/<id>/export?format=csv&gid=<tab>` (a private sheet gives
     a 401 / login page -> `VideoSheetError`).
   - **Deterministic parse, no LLM** (considered and rejected: risk of wrong
     numbers). Rules: a month's block starts at the row whose first cell is
     the month name; the header row is the first of the next three rows
     naming 3+ platforms; columns are found **by header name via
     `HEADER_NAMES` synonyms, never by position** (July 2026 added a column
     and swapped FB/IG); labels on the month row count too ("Video Type" moved
     there); date/title default to columns A/B (unlabelled before July);
     video rows run until a row lacks date or title. "N/A", "-", blank ->
     None. Money: `R199,27` decimal comma, `R1,100` thousands.
   - **Totals are computed, never read from the sheet**: the sheet's own
     totals were wrong in Apr 2026 (cell typed "10, 526", skipped by SUM) and
     Oct 2026 (total row omits the first two videos).
   - Section: summary table (videos, views per platform, total, boost spend)
     vs previous month and year earlier, then one row per video with a total
     row. Rows/columns empty in all shown months are left out ("where
     available"). Comparison months without a sheet/block show n/a.
   - If this month can't be analysed (no sheet for the year, no month
     block, unrecognised header, download failure, or **any** unforeseen
     exception: the sheet is hand-edited) the Videos section is left out and
     a red notice at the **bottom** of the report ("Videos could not be
     analysed: <reason>") says why; a warning goes to stderr; the rest of the
     report still goes out (owner's request).
   - **Status: written; tested against the real 2026 sheet with fake Matomo.**

5. **Puzzles** (puzzles.groundup.org.za, its own Matomo site ID): visits and
   page views, plus the top 30 puzzle pages (`Actions.getPageUrls`, `flat=1`).
   `site_summary()` can be reused without a home page URL.
   - Summary: `site_summary()` + `print_summary(..., PUZZLE_SUMMARY_ROWS)`
     (visits, unique visitors, page views, unique page views, avg visit
     duration from `VisitsSummary.get` `avg_time_on_site`; with comparisons).
     Matomo has no site-wide avg time *on page*, so visit duration is used.
     The GroundUp summary (`SUMMARY_ROWS`) doesn't show visit duration.
   - Top pages (`print_top_pages`, `TOP_PUZZLE_PAGES`): path, views, unique
     views, avg time. Calendar month, not "up to today". Includes the home
     page and the six index pages (crossword, streetwise, groupup, quizzes,
     sudoku, target), as the owner wants.
   - **Status: done, verified against the real Matomo.**

6. **HTML output**: Jinja2 template (agreed). Must be email-safe: inline CSS,
   simple tables, no JavaScript, no external stylesheets. Changes shown as
   coloured ▲/▼ percentages. Planned flags: `--output FILE`, `--email`, maybe
   `--cache` for development.
   - **Size limit:** Gmail clips emails over ~102 KB. Per-cell `style="…"`
     made a report 259 KB, so cells use HTML attributes instead
     (`cellpadding` on tables, `align`/`nowrap` on cells, `bgcolor` on rows
     for header and striping); font/colour set once per table plus a small
     `<style>` in `<head>` for Outlook. Jinja `trim_blocks`/`lstrip_blocks`
     strip whitespace. A fake report with 113 article rows was ~70 KB;
     with Q&As and videos ~84 KB. Watch the margin when adding sections.
   - Colours from groundup.org.za's CSS: dark `#151f22` (header), cyan
     `#00b1f0` (accent), links `#0250bb`, beige `#ebebe0` (table headers);
     ▲ green `#1f8a5b`, ▼ red `#c0392b`.
   - Article slugs link to the article; puzzle paths to `PUZZLES_SITE_URL`
     (a constant in `report.py`). Default output `report-YYYYMM.html`
     (`*.html` is gitignored).
   - **Status: written, tested with fake data only.** `--email` comes with
     section 7.

7. **Email and cron**: send via SMTP (credentials in `local_settings.py`) to
   all@groundup on the 15th of each month, reporting on the previous month.
   Cron must compute `YYYYMM` itself, e.g.
   `$(date -d "last month" +\%Y\%m)` (escape `%` in crontab) or via a small
   wrapper script. Log output, and **notify on failure**: a report that never
   arrives without anyone noticing is the main risk.

## Web interface

`web.py`, a small Flask app, separate from the counter app (owner's choice:
keeps the two codebases independent).
- `/report/`: form listing the last `FORM_MONTHS` (24) finished months;
  submits to `/report/?month=YYYYMM`, which redirects (relatively) to
  `/report/YYYYMM/`. Only six-digit values are redirected (no open redirect).
- `/report/YYYYMM/`: `report.build_report(month)`; the page is exactly the
  email HTML so it can be copy-pasted into an email. Invalid/unfinished
  months 404; a data-source failure gives a readable 500 page, with the
  traceback in gunicorn's log.
- No auth in the app: nginx basic auth protects `/report/` (same users as
  `/stats/`). `ProxyFix(x_proto=1, x_host=1)` so redirects keep https.
- Server: same machine as the counter, gunicorn under systemd, nginx proxies
  `/report/` to it (routes include the `/report/` prefix; no prefix
  stripping). A real report takes ~6 s; timeouts 120 s for headroom.
- Local: `env/bin/flask --app web run --port 5001`, open
  http://127.0.0.1:5001/report/
- `web.py` sets `Cache-Control: no-store` itself. Don't use `add_header` in
  the nginx location: it would stop the server-level security headers
  (HSTS, nosniff, X-Frame-Options) being inherited.
- `deploy/`: `nginx-report.conf` (location block for the counter's server
  block: same basic auth as /stats/, `access_log off` to keep requests out
  of the pixel log, 120 s timeout), `gunicorn_statsreport.service` (as on the
  server: user `groundup`, `/home/groundup/statsreport`, gunicorn 2 workers,
  127.0.0.1:5001, `web:app`),
  `README.md` (install/update/troubleshooting steps).
- **Status: being deployed by the owner** (systemd unit installed; first
  attempt failed with 203/EXEC: virtualenv to be recreated on the server).

## Where it runs

On the GroundUp server via cron, but it must also run remotely (e.g. on the
owner's laptop). Everything is fetched over HTTP (Matomo API, GroundUp API,
counter API), so only the email settings and the spreadsheet location are
machine-specific.

## Next steps

1. Owner runs the HTML report (incl. Q&As) on real data and checks it in a browser
   (and ideally in Gmail/Outlook).
2. Email and cron are **on hold**: for the first few months the owner runs
   the report by hand and copy-pastes it from the browser into an email
   (Ctrl+A, Ctrl+C, paste into Gmail/Outlook). Keep the template paste-safe
   (inline styles, plain tables). When resumed: `--email` via `smtplib`
   (likely Google Workspace SMTP with an app password), then cron.
3. Open question from section 2: article avg time on page is very low
   (0:10-0:30), probably because Matomo can't time single-page visits without
   the heartbeat timer. Decide whether to enable it or drop the column.
   Checked Nov 2026: neither groundup.org.za nor the puzzles site sets
   `enableHeartBeatTimer`; owner is considering it. (groundup.org.za also
   loads Matomo Tag Manager; owner confirmed it doesn't double-count.)
