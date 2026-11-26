#!/usr/bin/env python3
"""GroundUp monthly stats report.

Usage:
    python report.py 202501      # report on January 2025

For now this prints the Matomo headline figures, popular articles and
republication counts as plain text. Later steps add videos, puzzles and HTML.
"""

import argparse
import datetime
import sys

from counter import republication_hits
from groundup import articles_published
from matomo import Matomo, article_pageviews, site_summary
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

# Only articles with more page views than this are listed.
ARTICLE_MIN_PAGEVIEWS = 1000

# Only articles with more republication hits than this are listed.
REPUBLISHED_MIN_HITS = 1000

# In the "Top sites" column, only sites with more hits than this are listed.
TOP_SITE_MIN_HITS = 500


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
    return parser.parse_args(argv)


# --- Formatting helpers (these move into the HTML template later) ---------

def fmt_value(value, kind):
    if value is None:
        return "n/a"
    if kind == "duration":
        minutes, seconds = divmod(round(float(value)), 60)
        return f"{minutes}:{seconds:02d}"
    return f"{int(value):,}"


def fmt_change(current, previous):
    """Percentage change, e.g. '+12.3%'. 'n/a' if it can't be computed."""
    if current is None or not previous:
        return "n/a"
    change = (float(current) - float(previous)) / float(previous) * 100
    return f"{change:+.1f}%"


def print_table(title, headers, rows):
    """Print a titled table: first column left-aligned, the rest right-aligned."""
    widths = [max(len(r[i]) for r in [headers] + rows) for i in range(len(headers))]
    print(f"\n{title}\n{'=' * len(title)}")
    for row in [headers] + rows:
        cells = [row[0].ljust(widths[0])]
        cells += [cell.rjust(w) for cell, w in zip(row[1:], widths[1:])]
        print("  ".join(cells))


def print_summary(title, months, summaries):
    """Print a table: this month, previous month, change, year earlier, change."""
    this, prev, last_year = summaries
    headers = ["", str(months[0]), str(months[1]), "Change",
               str(months[2]), "Change"]
    rows = []
    for key, label, kind in SUMMARY_ROWS:
        if key not in this:
            continue  # e.g. home page rows for a site with no home page URL
        rows.append([
            label,
            fmt_value(this[key], kind),
            fmt_value(prev[key], kind),
            fmt_change(this[key], prev[key]),
            fmt_value(last_year[key], kind),
            fmt_change(this[key], last_year[key]),
        ])

    print_table(title, headers, rows)


def popular_articles(articles, pageviews):
    """Join the article list to Matomo's figures and keep the popular ones.

    `articles` comes from groundup.articles_published(); `pageviews` from
    matomo.article_pageviews(). Returns copies of the article dicts with the
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


def print_articles(title, articles):
    """Print a table of articles: slug, published, views, unique, avg time."""
    headers = ["Article", "Published", "Views", "Unique views", "Avg time"]
    rows = [
        [
            a["slug"],
            a["published"].strftime("%d %b"),  # e.g. "01 Oct"
            fmt_value(a["pageviews"], "number"),
            fmt_value(a["unique_pageviews"], "number"),
            fmt_value(a["avg_time"], "duration"),
        ]
        for a in articles
    ]

    print_table(title, headers, rows)
    print(f"({len(articles)} articles with more than "
          f"{ARTICLE_MIN_PAGEVIEWS:,} views)")


def republished_articles(articles, hits):
    """Join the article list to the counter's figures and keep the popular ones.

    `articles` comes from groundup.articles_published(); `hits` from
    counter.republication_hits(), keyed by pk. Returns copies of the article
    dicts with "hits" and "sites" added, most hits first.
    """
    republished = []
    for article in articles:
        figures = hits.get(article["pk"])
        if figures and figures["hits"] > REPUBLISHED_MIN_HITS:
            republished.append({**article, **figures})
    republished.sort(key=lambda a: a["hits"], reverse=True)
    return republished


def print_republished(title, articles):
    """Print a table of articles: slug, published, sites, hits, top sites."""
    headers = ["Article", "Published", "Sites", "Hits", "Top sites"]
    rows = [
        [
            a["slug"],
            a["published"].strftime("%d %b"),
            fmt_value(a["sites"], "number"),
            fmt_value(a["hits"], "number"),
            # e.g. "news24.com (4,100), iol.co.za (900)"
            ", ".join(
                f"{site} ({hits:,})"
                for site, hits in a["top_sites"]
                if hits > TOP_SITE_MIN_HITS
            ),
        ]
        for a in articles
    ]

    print_table(title, headers, rows)
    print(f"({len(articles)} articles with more than "
          f"{REPUBLISHED_MIN_HITS:,} republication hits)")


def main(argv=None):
    args = parse_args(argv)
    month = args.month
    months = [month, month.previous(), month.year_earlier()]

    matomo = Matomo(settings.MATOMO_URL, settings.MATOMO_TOKEN)
    summaries = [
        site_summary(
            matomo,
            settings.MATOMO_SITE_ID_GROUNDUP,
            m,
            home_page_url=settings.MATOMO_HOME_PAGE_URL,
        )
        for m in months
    ]
    print_summary(f"GroundUp website: {month}", months, summaries)

    # --- Articles published in the month ----------------------------------
    # Views are counted from the 1st of the month up to today (when the report
    # is run). Starting on the 1st is the same as starting at each article's
    # publication, since an article has no views before it's published.
    today = datetime.date.today()
    articles = articles_published(settings.GROUNDUP_API_URL, month)
    pageviews = article_pageviews(
        matomo, settings.MATOMO_SITE_ID_GROUNDUP, month.first_day, today
    )
    window = f"{month.first_day:%d %b %Y} to {today:%d %b %Y}"
    print_articles(
        f"Articles published in {month}: views {window}",
        popular_articles(articles, pageviews),
    )

    # --- Republication of articles published in the month -------------------
    # Same counting window and article list as above, but a separate report:
    # an article can be widely republished without many views on GroundUp.
    hits = republication_hits(
        settings.COUNTER_URL,
        settings.COUNTER_USERNAME,
        settings.COUNTER_PASSWORD,
        month.first_day,
        today,
    )
    print_republished(
        f"Republication of articles published in {month}: hits {window}",
        republished_articles(articles, hits),
    )


if __name__ == "__main__":
    main()
