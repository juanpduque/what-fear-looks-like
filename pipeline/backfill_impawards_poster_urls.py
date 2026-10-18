#!/usr/bin/env python3
"""One-off backfill: pull_impawards_credits.py's poster_image_urls column was
empty for every matched row (the regex expected an absolute /YYYY/posters/x.jpg
path, but the real markup uses a page-relative posters/x.jpg). This re-fetches
each already-matched row's impawards_url and fills in poster_image_urls without
re-running the slug-matching logic.

  python3 backfill_impawards_poster_urls.py
"""

from __future__ import annotations

import csv
import re
import time
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
CREDITS = DATA / "impawards_credits.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PulpAnalytics-AnatomyOfFear/1.0; +personal research)"
}
POSTER_JPG_RE = re.compile(r'(?:href|src)\s*=\s*"?posters/([a-z0-9_]+\.jpg)', re.IGNORECASE)


def main():
    rows = list(csv.DictReader(CREDITS.open(encoding="utf-8")))
    todo = [r for r in rows if r["status"] == "matched" and not r["poster_image_urls"].strip()]
    print(f"total rows: {len(rows):,} | matched w/o poster urls: {len(todo):,}")

    session = requests.Session()
    ok = fail = 0
    for i, r in enumerate(todo, 1):
        year = r["matched_year"] or r["year"]
        try:
            resp = session.get(r["impawards_url"], headers=HEADERS, timeout=20)
            fns = POSTER_JPG_RE.findall(resp.text) if resp.status_code == 200 else []
        except requests.RequestException:
            fns = []
        if fns:
            urls = sorted({f"http://www.impawards.com/{year}/posters/{fn}" for fn in fns})
            r["poster_image_urls"] = "|".join(urls)
            ok += 1
        else:
            fail += 1
        time.sleep(0.15)
        if i % 200 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} ok={ok} fail={fail}", flush=True)

    with CREDITS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"done. ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
