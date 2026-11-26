"""Web interface to the stats report, at counter.groundup.org.za/report/.

    /report/          a form to choose the month
    /report/202610/   the report for October 2026

The report page is exactly the email HTML, with nothing added, so it can
be selected (Ctrl+A), copied and pasted into an email.

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


def finished_months(today=None):
    """The FORM_MONTHS most recent finished months, most recent first."""
    today = today or datetime.date.today()
    month = Month(today.year, today.month).previous()
    months = []
    for _ in range(FORM_MONTHS):
        months.append(month)
        month = month.previous()
    return months


@app.route("/report/")
def form():
    """The form. Submitting it comes back here as /report/?month=202610,
    which we redirect to /report/202610/ so each report has a tidy address."""
    choice = request.args.get("month", "")
    if re.fullmatch(r"\d{6}", choice):
        # A relative redirect, so it works whatever the site's address.
        return redirect(f"{choice}/")
    return render_template("form.html", months=finished_months())


@app.route("/report/<yyyymm>/")
def show_report(yyyymm):
    """Generate and show the report for one month (takes a few seconds)."""
    try:
        month = Month.parse(yyyymm)
    except ValueError as e:
        abort(404, str(e))
    if not month.has_finished():
        abort(404, f"{month} hasn't finished yet")

    try:
        return report.build_report(month)
    except Exception as e:
        # Matomo, the GroundUp API or the counter failed. Say so on the page;
        # the full details go to gunicorn's log.
        traceback.print_exc()
        message = f"{type(e).__name__}: {e}"
        return (
            f"<p>The report for {html.escape(str(month))} couldn't be "
            f"generated.</p><p>{html.escape(message)}</p>"
            f'<p><a href="../">Back</a></p>',
            500,
        )
