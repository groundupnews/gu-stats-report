"""Fetching republication counts from the GroundUp counter app.

Sites that republish a GroundUp article include a tracking pixel in it. The
counter app (https://counter.groundup.org.za, a separate Flask app) records
every time a pixel is loaded, with the site it was loaded from.

Its stats page has a CSV export, which we use:

    <COUNTER_URL>/stats/YYYYMMDD/YYYYMMDD?format=csv&exclude=<site>...

It returns one row per (article, republishing site) with the columns
article_id (the article's pk), article, article_url, referrer, hits,
search_url. The stats pages are behind nginx basic auth.
"""

import csv
import io

import requests

# GroundUp's own sites, which aren't republications. These are the same
# defaults the counter's stats form uses. "*" is a wildcard.
EXCLUDE_SITES = [
    "*.groundup.org.za",
    "groundup.org.za",
    "*.groundup.news",
    "groundup.news",
]


def republication_hits(counter_url, username, password, start, end, timeout=60):
    """Republication hits per article between two dates (inclusive).

    `start` and `end` are datetime.date objects. Returns a dict keyed by
    article pk (an int), e.g.

        {17291: {"hits": 5321,
                 "sites": 4,
                 "top_sites": [("news24.com", 4100), ("iol.co.za", 900),
                               ("dailymaverick.co.za", 300)]},
         ...}

    where "sites" is the number of different sites the hits came from and
    "top_sites" the (up to) three with the most hits, most first.
    """
    url = f"{counter_url.rstrip('/')}/stats/{start:%Y%m%d}/{end:%Y%m%d}"
    params = {"format": "csv", "exclude": EXCLUDE_SITES}  # a list => repeated
    response = requests.get(
        url, params=params, auth=(username, password), timeout=timeout
    )
    response.raise_for_status()

    totals = {}
    for row in csv.DictReader(io.StringIO(response.text)):
        if not row["article_id"]:
            continue  # a pixel not named after an article; can't be matched
        # Normally one row per site, but an article could have more than one
        # pixel name, so add up hits per site rather than per row.
        t = totals.setdefault(int(row["article_id"]), {"hits": 0, "sites": {}})
        hits = int(row["hits"])
        t["hits"] += hits
        t["sites"][row["referrer"]] = t["sites"].get(row["referrer"], 0) + hits

    for t in totals.values():
        per_site = t["sites"]  # e.g. {"news24.com": 4100, "iol.co.za": 900}
        t["sites"] = len(per_site)
        # Sort (site, hits) pairs by hits, most first, and keep three.
        t["top_sites"] = sorted(per_site.items(), key=lambda s: s[1], reverse=True)[:3]
    return totals
