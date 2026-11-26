#!/usr/bin/env python3
"""GroundUp monthly stats report.

Usage:
    python report.py 202501                  # writes report-202501.html
    python report.py 202501 --output x.html  # writes x.html
    python report.py 202501 --warnothers     # also warn about Matomo "Others" rows

Fetches the figures (Matomo, the GroundUp API, the republication counter,
the video Google Sheet) and renders them into an email-safe HTML page with
templates/report.html.
Emailing is still to come.
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

import jinja2

from counter import republication_hits
from groundup import articles_published
from matomo import Matomo, pageviews_by_path, site_summary
from periods import Month
from videos import VideoSheetError, fetch_sheet, month_videos, videos_summary

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

# How many of the most viewed Q&As to list.
TOP_QANDA_PAGES = 20

# A single Q&A's path, e.g. "/qanda/1325/". This leaves out the Q&A index
# page "/qanda/" (and its "?topic=..." versions, which Matomo combines into it).
QANDA_PATH = re.compile(r"/qanda/\d+/?")

# The video section's summary table, as for SUMMARY_ROWS. Rows with no
# figure in any of the three months are left out.
VIDEO_SUMMARY_ROWS = [
    ("videos", "Videos", "number"),
    ("fb", "Facebook views", "number"),
    ("ig", "Instagram views", "number"),
    ("tiktok", "TikTok views", "number"),
    ("yt", "YouTube views", "number"),
    ("total", "Total views", "number"),
    ("fb_boost", "Facebook boost", "money"),
    ("ig_boost", "Instagram boost", "money"),
    ("spent", "Total spent", "money"),
]

# The video table's columns: (key in videos.month_videos' dicts, heading,
# format). Columns with nothing in them that month are left out.
VIDEO_COLUMNS = [
    ("date", "Date", "date"),
    ("title", "Video", "text"),
    ("type", "Type", "text"),
    ("fb", "Facebook", "number"),
    ("ig", "Instagram", "number"),
    ("tiktok", "TikTok", "number"),
    ("yt", "YouTube", "number"),
    ("total", "Total", "number"),
    ("fb_boost", "FB boost", "money"),
    ("ig_boost", "IG boost", "money"),
    ("spent", "Spent", "money"),
]

# Pages are linked to these sites (Matomo gives us only their paths).
GROUNDUP_SITE_URL = "https://groundup.org.za"
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


def money(rands):
    """1100 -> 'R1,100'; 199.27 -> 'R199.27'."""
    if rands is None:
        return "n/a"
    if rands == int(rands):
        return f"R{int(rands):,}"
    return f"R{rands:,.2f}"


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


def top_pages(pageviews, how_many):
    """The `how_many` most viewed pages, most first.

    `pageviews` comes from matomo.pageviews_by_path(), keyed by path. Returns
    a list of its figures dicts, each with "path" added.
    """
    pages = [{"path": path, **figures} for path, figures in pageviews.items()]
    pages.sort(key=lambda p: p["pageviews"], reverse=True)
    return pages[:how_many]


def video_section(month, months):
    """Everything the template needs for the video section, as a dict.

    Reads the video sheet(s) listed in settings.VIDEO_SHEETS (one per year).
    If this month's videos can't be analysed, returns {"error": reason}: the
    report then leaves the section out and says why at the bottom, and the
    rest still goes out. A missing comparison month (previous month, year
    earlier) just shows as n/a.

    Any error is caught, not only VideoSheetError: the sheet is edited by
    hand, so an unforeseen change mustn't stop the whole report.
    """
    sheets = getattr(settings, "VIDEO_SHEETS", {})
    downloaded = {}  # year -> rows, so each sheet is fetched only once

    def videos_for(m):
        if m.year not in sheets:
            raise VideoSheetError(f"no sheet for {m.year} in VIDEO_SHEETS")
        if m.year not in downloaded:
            downloaded[m.year] = fetch_sheet(sheets[m.year])
        return month_videos(downloaded[m.year], m)

    try:
        videos = videos_for(month)
    except VideoSheetError as e:
        print(f"Warning: video section left out: {e}", file=sys.stderr)
        return {"error": str(e)}
    except Exception as e:  # something videos.py didn't foresee
        reason = f"unexpected error ({type(e).__name__}: {e})"
        print(f"Warning: video section left out: {reason}", file=sys.stderr)
        return {"error": reason}

    summaries = [videos_summary(videos)]
    for m in months[1:]:
        try:
            summaries.append(videos_summary(videos_for(m)))
        except Exception:  # VideoSheetError or anything unforeseen
            # Same keys, all None, so every figure shows as n/a.
            summaries.append(dict.fromkeys(summaries[0]))

    def has_figure(value):
        return value not in (None, "")

    columns = [col for col in VIDEO_COLUMNS
               if any(has_figure(v[col[0]]) for v in videos)]
    return {
        "videos": videos,
        # Only rows and columns that have something in them.
        "summary_rows": [row for row in VIDEO_SUMMARY_ROWS
                         if any(has_figure(s[row[0]]) for s in summaries)],
        "summaries": summaries,
        "columns": columns,
        # (heading, alignment) pairs for the template's table_start.
        "headers": [(heading, "right" if kind in ("number", "money") else "left")
                    for key, heading, kind in columns],
    }


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
    env.filters["money"] = money
    env.filters["pct_change"] = pct_change
    return env.get_template("report.html").render(context)


def build_report(month, warn_others=False):
    """Fetch all the figures for `month` (a periods.Month) and return the
    report as an HTML string. Used by the command line (main() below) and
    the web interface (web.py)."""
    months = [month, month.previous(), month.year_earlier()]
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
        warn_others=warn_others,
    )

    # --- 2b. Most viewed Q&As ---------------------------------------------------
    # Q&As are read for years after publication, so this is the most viewed
    # Q&As in the calendar month, whenever they were published.
    qanda_pageviews = pageviews_by_path(
        matomo,
        settings.MATOMO_SITE_ID_GROUNDUP,
        period="month",
        date=month.matomo_date,
        path_prefix="/qanda/",
        warn_others=warn_others,
    )
    # Keep single Q&As only, not the index page.
    qanda_pageviews = {
        path: figures for path, figures in qanda_pageviews.items()
        if QANDA_PATH.fullmatch(path)
    }

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

    # --- 4. Videos (from the hand-maintained Google Sheet) -------------------
    video = video_section(month, months)

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
        warn_others=warn_others,
    )

    # --- Render the HTML ---------------------------------------------------------
    return render_report({
        "month": month,
        "months": months,
        "generated": datetime.datetime.now().strftime("%-d %B %Y, %H:%M"),
        "window": f"{month.first_day:%-d %b %Y} to {today:%-d %b %Y}",
        "groundup_summaries": groundup_summaries,
        "summary_rows": SUMMARY_ROWS,
        "articles": popular_articles(articles, pageviews),
        "article_min_pageviews": ARTICLE_MIN_PAGEVIEWS,
        "qanda_pages": top_pages(qanda_pageviews, TOP_QANDA_PAGES),
        "groundup_site_url": GROUNDUP_SITE_URL,
        "republished": republished_articles(articles, hits),
        "republished_min_hits": REPUBLISHED_MIN_HITS,
        "top_site_min_hits": TOP_SITE_MIN_HITS,
        "video": video,
        "puzzle_summaries": puzzle_summaries,
        "puzzle_summary_rows": PUZZLE_SUMMARY_ROWS,
        "puzzle_pages": top_pages(puzzle_pageviews, TOP_PUZZLE_PAGES),
        "puzzles_site_url": PUZZLES_SITE_URL,
    })


def main(argv=None):
    """Command line: build the report and write it to a file."""
    args = parse_args(argv)
    month = args.month
    output = args.output or f"report-{month.year}{month.month:02d}.html"
    html = build_report(month, warn_others=args.warnothers)
    Path(output).write_text(html, encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
