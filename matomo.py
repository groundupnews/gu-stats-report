"""Fetching figures from Matomo's Reporting API.

Matomo's API is a single URL (https://<matomo>/index.php). You choose what
you want with a `method` parameter, e.g. VisitsSummary.get, and say which
site and period with `idSite`, `period` and `date`. Matomo answers with JSON.

Docs: https://developer.matomo.org/api-reference/reporting-api
"""

import sys
from urllib.parse import urlsplit

import requests


class MatomoError(Exception):
    """Matomo returned an error (it does so with HTTP 200 and a JSON message)."""


class Matomo:
    """A minimal Matomo API client."""

    def __init__(self, base_url, token, timeout=60):
        self.api_url = base_url.rstrip("/") + "/index.php"
        self.token = token
        self.timeout = timeout

    def call(self, method, **params):
        """Call one API method and return the decoded JSON.

        The token is sent in the POST body rather than the URL so it doesn't
        end up in web server logs; Matomo recommends this.
        """
        query = {"module": "API", "method": method, "format": "JSON", **params}
        response = requests.post(
            self.api_url,
            params=query,
            data={"token_auth": self.token},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("result") == "error":
            raise MatomoError(f"{method}: {data.get('message')}")
        return data


def _as_dict(data):
    """Matomo returns [] instead of {} when a period has no data at all."""
    return data if isinstance(data, dict) else {}


def site_summary(matomo, site_id, month, home_page_url=None):
    """Headline figures for one site for one month.

    Returns a dict. A value is None when Matomo didn't provide it (e.g.
    unique visitors when monthly unique-visitor processing is switched off).
    """
    period = {"idSite": site_id, "period": "month", "date": month.matomo_date}

    visits = _as_dict(matomo.call("VisitsSummary.get", **period))
    actions = _as_dict(matomo.call("Actions.get", **period))

    summary = {
        "visits": visits.get("nb_visits"),
        "unique_visitors": visits.get("nb_uniq_visitors"),
        "pageviews": actions.get("nb_pageviews"),
        "unique_pageviews": actions.get("nb_uniq_pageviews"),
    }

    if home_page_url:
        # getPageUrl returns a list of matching rows; normally just one.
        rows = matomo.call("Actions.getPageUrl", pageUrl=home_page_url, **period)
        row = rows[0] if rows else {}
        summary["home_pageviews"] = row.get("nb_hits")
        summary["home_avg_time"] = row.get("avg_time_on_page")  # seconds

    return summary


def article_pageviews(matomo, site_id, start, end):
    """Page views of every article page between two dates (inclusive).

    `start` and `end` are datetime.date objects. Makes one API call and
    returns a dict keyed by path, e.g.

        {"/article/some-slug/": {"pageviews": 1234,
                                 "unique_pageviews": 1100,
                                 "avg_time": 95.0},   # seconds
         ...}

    If Matomo has recorded the same article under several URLs that differ
    only by query string (e.g. "?utm_source=facebook"), they are added
    together under the plain path.
    """
    rows = matomo.call(
        "Actions.getPageUrls",
        idSite=site_id,
        period="range",
        date=f"{start.isoformat()},{end.isoformat()}",
        flat=1,                   # one row per page, not nested by folder
        filter_limit=-1,          # all rows, not just the top 100
        filter_pattern="article", # only pages with "article" in the label
    )

    totals = {}
    for row in rows:
        # Each page row has the full URL it was recorded with. Rows without
        # one (e.g. Matomo's "Others" summary row) can't be matched; skip them.
        # But warn: an "Others" row means Matomo truncated its archives and
        # some articles' views are being undercounted.
        if "url" not in row:
            print(f"Warning: Matomo row {row.get('label')!r} with "
                  f"{row.get('nb_hits')} page views has no URL; skipped.",
                  file=sys.stderr)
            continue
        path = urlsplit(row["url"]).path  # drops domain and query string
        if not path.startswith("/article/"):
            continue

        pageviews = row.get("nb_hits", 0)
        t = totals.setdefault(path, {"pageviews": 0, "unique_pageviews": 0,
                                     "time_x_views": 0})
        t["pageviews"] += pageviews
        t["unique_pageviews"] += row.get("nb_visits", 0)
        # To combine averages from several rows correctly, weight each by its
        # page views: (avg1 * views1 + avg2 * views2) / (views1 + views2).
        t["time_x_views"] += row.get("avg_time_on_page", 0) * pageviews

    for t in totals.values():
        time_x_views = t.pop("time_x_views")
        t["avg_time"] = time_x_views / t["pageviews"] if t["pageviews"] else None

    return totals
