"""Reading video view counts from the hand-maintained Google Sheet.

There is one sheet per year. On it, each month is a block of rows:

    October ,,,,Video views ,,,,,Video Type,FB Boost,IG Boost,Total Spent
    Date,Video,,Video Duration,FB,IG,TikTok,YT,Total views ,,,,
    7 October 2026,Art after prison...,,05:43,"34,641",-,-,"1,935",...
    ...one row per video...
    ,,,,"951,025","167,420",...          <- the sheet's total row

The layout varies between months (in July 2026 a column was added and
Facebook and Instagram swapped places), so columns are found by their
header names, never by position. The rules:

  1. A month's block starts at the row whose first cell is the month name.
  2. Its header row is the first of the next three rows that names at least
     three platforms. Labels on the month row itself (e.g. "Video Type")
     count too.
  3. Video rows follow, until the first row without a date or title.
  4. "N/A", "-" and blanks mean no figure. Totals are added up here, never
     taken from the sheet: the sheet's own total rows have been wrong.

If a block or its header can't be found, VideoSheetError is raised, so
the report says so rather than showing wrong numbers.

The sheet must be shared as "Anyone with the link can view": we download
a tab as CSV from https://docs.google.com/spreadsheets/d/<id>/export.
"""

import csv
import datetime
import io
import re

import requests

MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december"]

# Header labels as they appear in the sheet (lower case, trimmed) -> our
# name for the column. Add to this if someone uses a new label.
HEADER_NAMES = {
    "date": "date",
    "video": "title",
    "video type": "type",
    "facebook": "fb", "fb": "fb",
    "instagram": "ig", "ig": "ig",
    "tiktok": "tiktok", "tik tok": "tiktok",
    "youtube": "yt", "yt": "yt",
    "fb boost": "fb_boost",
    "ig boost": "ig_boost",
    "total spent": "spent",
}
PLATFORMS = ["fb", "ig", "tiktok", "yt"]
MONEY = ["fb_boost", "ig_boost", "spent"]


class VideoSheetError(Exception):
    """The sheet couldn't be read or a month's block couldn't be understood."""


def fetch_sheet(sheet_link, timeout=60):
    """Download one tab of a Google Sheet; return its rows as lists of strings.

    `sheet_link` is the sheet's normal address as copied from the browser,
    e.g. https://docs.google.com/spreadsheets/d/<id>/edit?gid=<tab>#gid=<tab>
    """
    sheet_id = re.search(r"/d/([\w-]+)", sheet_link)
    tab = re.search(r"gid=(\d+)", sheet_link)
    if not sheet_id:
        raise VideoSheetError(f"can't find a sheet ID in {sheet_link!r}")
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id.group(1)}/export"
           f"?format=csv&gid={tab.group(1) if tab else 0}")
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as e:  # no connection, timeout, ...
        raise VideoSheetError(f"couldn't download the sheet: {e}")
    if response.status_code != 200 or "text/csv" not in response.headers.get(
            "Content-Type", ""):
        # Google answers a private sheet with a login page, not an error.
        raise VideoSheetError(
            f"couldn't download the sheet (HTTP {response.status_code}); is it "
            "shared as 'Anyone with the link can view'?")
    return list(csv.reader(io.StringIO(response.text)))


def parse_number(text):
    """'1,234' or '10, 526' -> int; 'N/A', '-', '' -> None."""
    digits = text.replace(",", "").replace(" ", "")
    return int(digits) if digits.isdigit() else None


def parse_money(text):
    """'R1100' or 'R1,100' -> 1100.0; 'R199,27' -> 199.27; '' -> None.

    A comma followed by exactly two final digits is a decimal comma, as in
    'R199,27'; any other comma separates thousands.
    """
    text = text.upper().replace("R", "").replace(" ", "")
    if re.fullmatch(r"\d+,\d\d", text):
        text = text.replace(",", ".")
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(text):
    """'7 October 2026' or '09 February' -> datetime.date, else None.

    Only used for display; a date we can't read is shown as typed.
    """
    for fmt in ("%d %B %Y", "%d %B"):
        try:
            return datetime.datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    return None


def month_videos(rows, month):
    """The videos listed for `month` (a periods.Month) in a year's sheet.

    Returns a list of dicts with keys: date (datetime.date or None),
    date_text, title, type, fb, ig, tiktok, yt, total, fb_boost, ig_boost,
    spent. Figures the sheet doesn't have are None. Raises VideoSheetError
    if the month's block or its header row can't be found.
    """
    name = MONTH_NAMES[month.month - 1]

    # 1. The block starts at the row whose first cell is the month name.
    start = next((i for i, row in enumerate(rows)
                  if row and row[0].strip().lower() == name), None)
    if start is None:
        raise VideoSheetError(f"no {name.title()} section in the sheet")

    # 2. The header row: the first of the next three rows naming 3+ platforms.
    def labels(row):
        return [cell.strip().lower() for cell in row]

    header = next((i for i in range(start, min(start + 3, len(rows)))
                   if sum(HEADER_NAMES.get(c) in PLATFORMS
                          for c in labels(rows[i])) >= 3), None)
    if header is None:
        raise VideoSheetError(
            f"can't find the header row (Facebook, Instagram, ...) for "
            f"{name.title()}")

    # Map our column names to positions, using the month row and the
    # header row (from July 2026, "Video Type" etc. sit on the month row).
    columns = {}
    for i in sorted({start, header}):
        for position, label in enumerate(labels(rows[i])):
            if label in HEADER_NAMES:
                columns[HEADER_NAMES[label]] = position
    # Until June 2026 the date and title columns had no labels.
    columns.setdefault("date", 0)
    columns.setdefault("title", 1)

    def cell(row, key):
        position = columns.get(key)
        return row[position].strip() if position is not None and position < len(row) else ""

    # 3. Video rows, until the first row without a date or title.
    videos = []
    for row in rows[header + 1:]:
        if not cell(row, "date") or not cell(row, "title"):
            break
        video = {
            "date": parse_date(cell(row, "date")),
            "date_text": cell(row, "date"),
            "title": cell(row, "title"),
            "type": cell(row, "type"),
        }
        for key in PLATFORMS:
            video[key] = parse_number(cell(row, key))
        for key in MONEY:
            video[key] = parse_money(cell(row, key))
        # 4. Our own total: the sum of the platforms that have a figure.
        figures = [video[key] for key in PLATFORMS if video[key] is not None]
        video["total"] = sum(figures) if figures else None
        videos.append(video)
    return videos


def videos_summary(videos):
    """Totals for a month's videos, for the summary table: the number of
    videos, views per platform and overall, and boost spend. A total is
    None if no video has that figure."""
    def total(key):
        figures = [v[key] for v in videos if v[key] is not None]
        return sum(figures) if figures else None

    summary = {"videos": len(videos)}
    for key in PLATFORMS + ["total"] + MONEY:
        summary[key] = total(key)
    return summary
