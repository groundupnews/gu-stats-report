"""Fetching data from the GroundUp website's own API.

The GroundUp site has an endpoint that lists the articles published in a
month:

    https://groundup.org.za/api/articles/<year>/<month>/

It returns JSON like this:

    {"count": 125,
     "articles": [{"pk": 15900,
                   "url": "https://groundup.org.za/article/some-slug/",
                   "published": "2025-10-01T01:00:00+00:00"},
                  ...]}

Months are in UTC, as are the "published" times.
"""

import datetime
from urllib.parse import urlsplit

import requests


def articles_published(api_url, month, timeout=60):
    """The articles published in `month` (a periods.Month), oldest first.

    `api_url` is the base of the API, e.g. "https://groundup.org.za/api".

    Returns a list of dicts, one per article, with keys:
        pk         the article's primary key (an int)
        url        its full URL
        path       just the path part, e.g. "/article/some-slug/"; we use
                   this to match the article with Matomo's figures
        slug       e.g. "some-slug"; shown in the report as the link text
        published  publication time as a timezone-aware datetime (UTC)
    """
    url = f"{api_url.rstrip('/')}/articles/{month.year}/{month.month}/"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()

    articles = []
    for item in response.json()["articles"]:
        path = urlsplit(item["url"]).path  # drops "https://groundup.org.za"
        articles.append({
            "pk": item["pk"],
            "url": item["url"],
            "path": path,
            # "/article/some-slug/" -> ["", "article", "some-slug", ""]
            "slug": path.strip("/").split("/")[-1],
            "published": datetime.datetime.fromisoformat(item["published"]),
        })

    articles.sort(key=lambda a: a["published"])
    return articles
