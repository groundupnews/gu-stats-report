"""Fetching figures from Matomo's Reporting API.

Matomo's API is a single URL (https://<matomo>/index.php). You choose what
you want with a `method` parameter, e.g. VisitsSummary.get, and say which
site and period with `idSite`, `period` and `date`. Matomo answers with JSON.

Docs: https://developer.matomo.org/api-reference/reporting-api
"""

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
