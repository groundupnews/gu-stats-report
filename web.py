"""Web interface to the stats report, at counter.groundup.org.za/report/.

    /report/                     a form to choose the month
    /report/202610/              the report for October 2026
    /report/202610/regenerate/   (POST) make a fresh one

A report is generated the first time it's asked for and saved in reports/;
after that the saved copy is shown until someone presses Regenerate.

The report page is the email HTML plus a small toolbar at the top (added
as the page is sent, never saved). The toolbar is marked so that selecting
the page (Ctrl+A) and copying leaves it out of the email.

There's no login here: like the counter's /stats/ pages, /report/ is
protected by nginx basic auth. Don't expose this app without it.

Run locally, then open http://127.0.0.1:5001/report/ :
    env/bin/flask --app web run --port 5001
On the server it runs under gunicorn behind nginx (see deploy/).
"""

import datetime
import html
import re
import traceback
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

import report
from periods import Month

app = Flask(__name__)  # finds its templates in templates/ next to this file

# Behind nginx, believe its X-Forwarded-Proto and X-Forwarded-Host headers,
# so redirects (e.g. /report -> /report/) keep https and the right host.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# How many past months the form offers.
FORM_MONTHS = 24

# Generated reports are saved here, one file per month, and shown again
# without regenerating until someone presses Regenerate.
REPORTS_DIR = Path(__file__).parent / "reports"


@app.after_request
def no_caching(response):
    """Tell browsers (and any proxy) not to store these pages: they hold
    internal figures, and a cached report would hide newer numbers. Set here
    rather than in nginx, where an add_header in the location block would
    switch off the server's security headers."""
    response.headers["Cache-Control"] = "no-store"
    return response


def finished_months(today=None):
    """The FORM_MONTHS most recent finished months, most recent first."""
    today = today or datetime.date.today()
    month = Month(today.year, today.month).previous()
    months = []
    for _ in range(FORM_MONTHS):
        months.append(month)
        month = month.previous()
    return months


def report_file(month):
    """Where the saved report for `month` is kept."""
    return REPORTS_DIR / f"report-{month.year}{month.month:02d}.html"


def finished_month(yyyymm):
    """Turn the YYYYMM in an address into a Month, or give a 404 page."""
    try:
        month = Month.parse(yyyymm)
    except ValueError as e:
        abort(404, str(e))
    if not month.has_finished():
        abort(404, f"{month} hasn't finished yet")
    return month


def generate(month):
    """Generate the report for `month` and save it, replacing any saved one."""
    page = report.build_report(month)
    REPORTS_DIR.mkdir(exist_ok=True)
    # Write to a temporary file, then rename it: the rename is instant, so
    # nobody ever sees a half-written report.
    path = report_file(month)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(page, encoding="utf-8")
    temporary.replace(path)


def error_page(month, error, kept_saved):
    """Matomo, the GroundUp API or the counter failed: say so on the page.
    The full details go to gunicorn's log."""
    traceback.print_exc()
    message = f"{type(error).__name__}: {error}"
    kept = ("<p>The previously saved report is unchanged.</p>"
            if kept_saved else "")
    return (
        f"<p>The report for {html.escape(str(month))} couldn't be "
        f"generated.</p><p>{html.escape(message)}</p>{kept}"
        f'<p><a href="/report/">Back</a></p>',
        500,
    )


@app.route("/report/")
def form():
    """The form. Submitting it comes back here as /report/?month=202610,
    which we redirect to /report/202610/ so each report has a tidy address."""
    choice = request.args.get("month", "")
    if re.fullmatch(r"\d{6}", choice):
        # A relative redirect, so it works whatever the site's address.
        return redirect(f"{choice}/")
    options = []
    for month in finished_months():
        label = str(month)
        if report_file(month).exists():
            label += " (saved)"
        options.append((f"{month.year}{month.month:02d}", label))
    return render_template("form.html", options=options)


@app.route("/report/<yyyymm>/")
def show_report(yyyymm):
    """Show the saved report for one month, generating it first if there
    isn't one yet (that takes a few seconds)."""
    month = finished_month(yyyymm)
    path = report_file(month)
    if not path.exists():
        try:
            generate(month)
        except Exception as e:
            return error_page(month, e, kept_saved=False)

    # Add the toolbar (Regenerate etc.) to the page as it's sent. It isn't
    # part of the saved report, so it can never end up in an email by way
    # of the saved file; it's also marked so Ctrl+A copying skips it.
    page = path.read_text(encoding="utf-8")
    saved_at = datetime.datetime.fromtimestamp(path.stat().st_mtime)
    toolbar = render_template(
        "toolbar.html", month=month,
        saved_at=saved_at.strftime("%-d %B %Y at %H:%M"))
    body = page.index(">", page.index("<body")) + 1  # just after <body ...>
    return page[:body] + toolbar + page[body:]


@app.route("/report/<yyyymm>/regenerate/", methods=["POST"])
def regenerate(yyyymm):
    """The Regenerate button: make a fresh report, then show it. Only POST,
    so a link-prefetching browser or a bot can't trigger it by accident."""
    month = finished_month(yyyymm)
    try:
        generate(month)
    except Exception as e:
        return error_page(month, e, kept_saved=report_file(month).exists())
    # 303 tells the browser to follow with a GET: back to /report/YYYYMM/.
    return redirect("../", code=303)
