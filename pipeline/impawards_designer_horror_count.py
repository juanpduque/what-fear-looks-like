#!/usr/bin/env python3
"""For the top design agencies/illustrators found in data/impawards_credits.csv,
scrape their full impawards.com credit page (every genre, not just horror) and
cross-reference it against the horror corpus (data/census.csv) to see how much
of each designer's total output is horror.

Each designer page lists every poster they're credited on as (year, slug) pairs
with no title text, so matching works by regenerating the same slug candidates
used by pull_impawards_credits.py for every census.csv title and checking for
overlap — this also recovers horror matches the original run missed (e.g. a
poster that exists on impawards.com under a slug variant we didn't try).

  python3 impawards_designer_horror_count.py --top 15
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from collections import Counter
from pathlib import Path

import requests

from pull_impawards_credits import slug_variants

DATA = Path(__file__).resolve().parent / "data"
CREDITS = DATA / "impawards_credits.csv"
CENSUS = DATA / "census.csv"
OUT = DATA / "impawards_designer_horror_counts.csv"
BASE = "http://www.impawards.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PulpAnalytics-AnatomyOfFear/1.0; +personal research)"
}

CREDIT_LINK_RE = re.compile(r"href\s*=\s*/(\d{4})/([a-z0-9_]+)\.html><img", re.IGNORECASE)
INDEX_ENTRY_RE = re.compile(
    r"<a href\s*=\s*([a-z0-9_./-]+\.html)><b>([^<]+)</b></a>\s*\((\d+)\)", re.IGNORECASE
)


def load_top_names(top_n: int) -> list[str]:
    rows = list(csv.DictReader(CREDITS.open(encoding="utf-8")))
    names = Counter()
    for r in rows:
        for col in ("poster_designer", "poster_illustrator"):
            v = r.get(col, "").strip()
            if v:
                names[v] += 1
    return [name for name, _ in names.most_common(top_n)]


def build_name_to_slug(session: requests.Session) -> dict[str, str]:
    html = session.get(f"{BASE}/designers/index.html", headers=HEADERS, timeout=30).text
    out = {}
    for href, name, _count in INDEX_ENTRY_RE.findall(html):
        out[name.strip()] = href.strip()
    return out


def designer_credit_set(session: requests.Session, slug_path: str) -> set[tuple[int, str]]:
    url = f"{BASE}/designers/{slug_path}" if not slug_path.startswith("/") else f"{BASE}{slug_path}"
    for _attempt in range(3):
        try:
            r = session.get(url, headers=HEADERS, timeout=60)
            if r.status_code != 200:
                return set()
            return {(int(y), s.lower()) for y, s in CREDIT_LINK_RE.findall(r.text)}
        except requests.RequestException:
            time.sleep(2)
    return set()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    names = load_top_names(args.top)
    print(f"top {len(names)} designers/illustrators by credited horror posters so far:")
    for n in names:
        print(f"  {n}")

    census = list(csv.DictReader(CENSUS.open(encoding="utf-8")))
    # precompute slug candidates per census row once
    census_slugs = []
    for r in census:
        try:
            year = int(float(r["year"]))
        except (TypeError, ValueError):
            continue
        for s in slug_variants(r["title"]):
            for off in (-1, 0, 1):
                census_slugs.append((year + off, s, r["id"], r["title"], year))

    lookup = {}
    for y, s, mid, title, orig_year in census_slugs:
        lookup.setdefault((y, s), (mid, title, orig_year))

    session = requests.Session()
    name_to_slug = build_name_to_slug(session)

    rows_out = []
    norm_index = {_norm(k): v for k, v in name_to_slug.items()}

    for name in names:
        slug_path = name_to_slug.get(name) or norm_index.get(_norm(name))
        if not slug_path:
            # fall back to substring match (handles "BLT Communications, LLC" vs "BLT Communications")
            n = _norm(name)
            candidates = [v for k, v in norm_index.items() if n in k or k in n]
            slug_path = candidates[0] if candidates else None
        if not slug_path:
            print(f"  [skip] no designer page slug found for {name!r}")
            continue
        time.sleep(0.3)
        credits = designer_credit_set(session, slug_path)
        matches = {}
        for y, s in credits:
            for variant_y in (y, y - 1, y + 1):
                hit = lookup.get((variant_y, s))
                if hit:
                    matches[hit[0]] = hit  # dedupe by census id
                    break
        print(
            f"{name}: {len(credits)} total impawards credits (any genre), "
            f"{len(matches)} match your horror corpus"
        )
        rows_out.append(
            {
                "name": name,
                "total_impawards_credits": len(credits),
                "horror_corpus_matches": len(matches),
                "matched_titles": "|".join(sorted(f"{t} ({y})" for _, t, y in matches.values())),
            }
        )

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "name",
                "total_impawards_credits",
                "horror_corpus_matches",
                "matched_titles",
            ],
        )
        w.writeheader()
        w.writerows(rows_out)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
