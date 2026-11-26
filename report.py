#!/usr/bin/env python3
"""GroundUp monthly stats report.

Usage:
    python report.py 202501      # report on January 2025

For now this prints the Matomo headline figures as plain text. Later steps
add the article tables, republication counts, videos, puzzles and HTML.
"""

import argparse
import sys

from matomo import Matomo, site_summary
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

    widths = [max(len(r[i]) for r in [headers] + rows) for i in range(len(headers))]
    print(f"\n{title}\n{'=' * len(title)}")
    for row in [headers] + rows:
        cells = [row[0].ljust(widths[0])]
        cells += [cell.rjust(w) for cell, w in zip(row[1:], widths[1:])]
        print("  ".join(cells))


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


if __name__ == "__main__":
    main()
