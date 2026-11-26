#!/usr/bin/env python3
"""GroundUp monthly stats report.

Usage:
    python report.py 202501                  # writes report-202501.html
    python report.py 202501 --output x.html  # writes x.html
    python report.py 202501 --warnothers     # also warn about Matomo "Others" rows

Fetches the figures (Matomo, the GroundUp API, the republication counter)
and renders them into an email-safe HTML page with templates/report.html.
Videos and emailing are still to come.
"""

import argparse
import datetime
import sys
from pathlib import Path

import jinja2

from counter import republication_hits
from groundup import articles_published
from matomo import Matomo, pageviews_by_path, site_summary
from periods import Month

try:
    import local_settings as settings
except ImportError:
    sys.exit(
        "local_settings.py not found. Copy local_settings.example.py to "
        "local_settings.py and fill in your values."
    )


# The rows of the summary table: (key in site_summary's dict, label, format).
SUMMARY_ROWS = [
    ("visits", "Visits", "number"),
    ("unique_visitors", "Unique visitors", "number"),
    ("pageviews", "Page views", "number"),
    ("unique_pageviews", "Unique page views", "number"),
    ("home_pageviews", "Home page views", "number"),
    ("home_avg_time", "Avg time on home page", "duration"),
]

# The puzzles site has no home page rows, but does show visit duration.
PUZZLE_SUMMARY_ROWS = [
    ("visits", "Visits", "number"),
    ("unique_visitors", "Unique visitors", "number"),
    ("pageviews", "Page views", "number"),
    ("unique_pageviews", "Unique page views", "number"),
    ("avg_visit_time", "Avg visit duration", "duration"),
]

# Only articles with more page views than this are listed.
ARTICLE_MIN_PAGEVIEWS = 1000

# Only articles with more republication hits than this are listed.
REPUBLISHED_MIN_HITS = 1000

# In the "Top sites" column, only sites with more hits than this are listed.
TOP_SITE_MIN_HITS = 500

# How many of the puzzles site's most viewed pages to list.
TOP_PUZZLE_PAGES = 30

# Puzzle pages are linked to this site (Matomo gives us only their paths).
PUZZLES_SITE_URL = "https://puzzles.groundup.org.za"

# The HTML template lives in templates/ next to this file. Using this file's
# location (rather than the current directory) means cron can run the script
# from anywhere.
TEMPLATES_DIR = Path(__file__).parent / "templates"


def month_arg(text):
    """argparse 'type' function: turns 'YYYYMM' into a Month."""
    try:
        month = Month.parse(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))
    if not month.has_finished():
        raise argparse.ArgumentTypeError(f"{month} hasn't finished yet")
    return month


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="GroundUp monthly stats report")
    parser.add_argument(
        "month", type=month_arg, help="year and month to report on, as YYYYMM"
    )
    parser.add_argument(
        "--output",
        help="HTML file to write (default: report-YYYYMM.html)",
    )
    parser.add_argument(
        "--warnothers",
        action="store_true",  # False unless the flag is given
        help='warn about Matomo rows with no URL (e.g. "Others"), which mean '
             "some page views are undercounted",
    )
    return parser.parse_args(argv)


# --- Template filters --------------------------------------------------------
# Used in the template as {{ value|number }}, {{ value|duration }} and
# {{ current|pct_change(previous) }}. Missing values (None) show as "n/a".

def number(value):
    """1234567 -> '1,234,567'."""
    if value is None:
        return "n/a"
    return f"{int(value):,}"


def duration(seconds):
    """95 -> '1:35' (minutes:seconds)."""
    if seconds is None:
        return "n/a"
    minutes, seconds = divmod(round(float(seconds)), 60)
    return f"{minutes}:{seconds:02d}"


def pct_change(current, previous):
    """Percentage change from previous to current, e.g. 12.3, or None if it
    can't be computed. The template decides how to show it (colour, arrow)."""
    if current is None or not previous:
        return None
    return (float(current) - float(previous)) / float(previous) * 100


# --- Preparing the data --------------------------------------------------------

def popular_articles(articles, pageviews):
    """Join the article list to Matomo's figures and keep the popular ones.

    `articles` comes from groundup.articles_published(); `pageviews` from
    matomo.pageviews_by_path(). Returns copies of the article dicts with the
    Matomo figures added, most viewed first. An article Matomo has no row
    for has had no views, so it is left out.
    """
    popular = []
    for article in articles:
        figures = pageviews.get(article["path"])
        if figures and figures["pageviews"] > ARTICLE_MIN_PAGEVIEWS:
            popular.append({**article, **figures})  # merge the two dicts
    popular.sort(key=lambda a: a["pageviews"], reverse=True)
    return popular


def republished_articles(articles, hits):
    """Join the article list to the counter's figures and keep the popular ones.

    `articles` comes from groundup.articles_published(); `hits` from
    counter.republication_hits(), keyed by pk. Returns copies of the article
    dicts with "hits", "sites" and "top_sites" added, most hits first.
    "top_sites" keeps only sites with more than TOP_SITE_MIN_HITS hits.
    """
    republished = []
    for article in articles:
        figures = hits.get(article["pk"])
        if figures and figures["hits"] > REPUBLISHED_MIN_HITS:
            top_sites = [(site, n) for site, n in figures["top_sites"]
                         if n > TOP_SITE_MIN_HITS]
            republished.append({**article, **figures, "top_sites": top_sites})
    republished.sort(key=lambda a: a["hits"], reverse=True)
    return republished


def top_pages(pageviews):
    """The TOP_PUZZLE_PAGES most viewed pages, most first.

    `pageviews` comes from matomo.pageviews_by_path(), keyed by path. Returns
    a list of its figures dicts, each with "path" added.
    """
    pages = [{"path": path, **figures} for path, figures in pageviews.items()]
    pages.sort(key=lambda p: p["pageviews"], reverse=True)
    return pages[:TOP_PUZZLE_PAGES]


# --- Rendering -------------------------------------------------------------------

def render_report(context):
    """Fill in templates/report.html with the values in `context` (a dict)."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,  # escape <, & etc. in values, e.g. odd page paths
        # Don't leave a blank line or indentation behind wherever the
        # template has a {% ... %} tag on its own line. Keeps the email small.
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["number"] = number
    env.filters["duration"] = duration
    env.filters["pct_change"] = pct_change
    return env.get_template("report.html").render(context)


def main(argv=None):
    args = parse_args(argv)
    month = args.month
    months = [month, month.previous(), month.year_earlier()]
    output = args.output or f"report-{month.year}{month.month:02d}.html"
    matomo = Matomo(settings.MATOMO_URL, settings.MATOMO_TOKEN)

    # --- 1. GroundUp website headline figures -------------------------------
    groundup_summaries = [
        site_summary(
            matomo,
            settings.MATOMO_SITE_ID_GROUNDUP,
            m,
            home_page_url=settings.MATOMO_HOME_PAGE_URL,
        )
        for m in months
    ]

    # --- 2. Articles published in the month ----------------------------------
    # Views are counted from the 1st of the month up to today (when the report
    # is run). Starting on the 1st is the same as starting at each article's
    # publication, since an article has no views before it's published.
    today = datetime.date.today()
    articles = articles_published(settings.GROUNDUP_API_URL, month)
    pageviews = pageviews_by_path(
        matomo,
        settings.MATOMO_SITE_ID_GROUNDUP,
        period="range",
        date=f"{month.first_day.isoformat()},{today.isoformat()}",
        path_prefix="/article/",
        warn_others=args.warnothers,
    )

    # --- 3. Republication of articles published in the month -----------------
    # Same counting window and article list as above, but a separate report:
    # an article can be widely republished without many views on GroundUp.
    hits = republication_hits(
        settings.COUNTER_URL,
        settings.COUNTER_USERNAME,
        settings.COUNTER_PASSWORD,
        month.first_day,
        today,
    )

    # --- 5. Puzzles site -------------------------------------------------------
    # Its own Matomo site. Calendar month only (no "up to today" window):
    # puzzles aren't tied to a publication date in our data.
    puzzle_summaries = [
        site_summary(matomo, settings.MATOMO_SITE_ID_PUZZLES, m) for m in months
    ]
    puzzle_pageviews = pageviews_by_path(
        matomo,
        settings.MATOMO_SITE_ID_PUZZLES,
        period="month",
        date=month.matomo_date,
        warn_others=args.warnothers,
    )

    # --- Render and write the HTML ------------------------------------------
    html = render_report({
        "month": month,
        "months": months,
        "generated": datetime.datetime.now().strftime("%-d %B %Y, %H:%M"),
        "window": f"{month.first_day:%-d %b %Y} to {today:%-d %b %Y}",
        "groundup_summaries": groundup_summaries,
        "summary_rows": SUMMARY_ROWS,
        "articles": popular_articles(articles, pageviews),
        "article_min_pageviews": ARTICLE_MIN_PAGEVIEWS,
        "republished": republished_articles(articles, hits),
        "republished_min_hits": REPUBLISHED_MIN_HITS,
        "top_site_min_hits": TOP_SITE_MIN_HITS,
        "puzzle_summaries": puzzle_summaries,
        "puzzle_summary_rows": PUZZLE_SUMMARY_ROWS,
        "puzzle_pages": top_pages(puzzle_pageviews),
        "puzzles_site_url": PUZZLES_SITE_URL,
    })
    Path(output).write_text(html, encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
