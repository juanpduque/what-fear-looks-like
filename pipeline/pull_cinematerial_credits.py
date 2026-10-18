#!/usr/bin/env python3
"""Cross-reference CineMaterial's design-company + artist directories against the
horror corpus to recover poster credits CineMaterial doesn't show on the movie
page itself.

Unlike impawards.com, a CineMaterial movie/poster page carries no designer or
artist credit at all -- the only place the association exists is on the
company's or artist's own gallery page (e.g. cinematerial.com/companies/X lists
every poster credited to X). So this script works in reverse from
pull_impawards_credits.py: it walks the full company + artist directories,
scrapes each entity's paginated gallery for (imdb_id, title, year) triples, and
matches those against data/census.csv -- by imdb_id when known (joined in from
data/horror_movies.csv), falling back to normalized title+year.

CineMaterial movie URLs redirect on the numeric "-iNNNNNNN" suffix alone (it is
the IMDb numeric id, confirmed against the page's own schema.org JSON-LD), so no
slug-guessing is needed once we have that id from a gallery listing.

Checkpointed like pull_impawards_credits.py: reruns skip entities already
present in the output CSV.

  python3 pull_cinematerial_credits.py --limit 50          # sample test run
  python3 pull_cinematerial_credits.py --rate 6            # continue full run
"""

from __future__ import annotations

import argparse
import csv
import re
import time
import unicodedata
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
CENSUS = DATA / "census.csv"
HORROR_MOVIES = DATA / "horror_movies.csv"
ENTITIES_OUT = DATA / "cinematerial_entity_progress.csv"
CREDITS_OUT = DATA / "cinematerial_credits.csv"
BASE = "https://www.cinematerial.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PulpAnalytics-AnatomyOfFear/1.0; +personal research)"
}

INDEX_ENTRY_RE = re.compile(
    r'href="(/(?:companies|artists)/[a-z0-9-]+)"[^>]*>([^<]+)</a>', re.IGNORECASE
)
GALLERY_ITEM_RE = re.compile(
    r'href="/movies/[a-z0-9-]+-i(\d+)"[^>]*>([^<]+)</a>\s*<span[^>]*>(\d{4})</span>',
    re.IGNORECASE,
)
HAS_NEXT_RE = re.compile(r"page=(\d+)\"[^>]*>\s*Next", re.IGNORECASE)


def norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    t = t.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", t.lower())


def fetch(session: requests.Session, url: str, retries: int = 3) -> str | None:
    for _ in range(retries):
        try:
            r = session.get(url, headers=HEADERS, timeout=45)
            if r.status_code == 200:
                return r.text
            return None
        except requests.RequestException:
            time.sleep(2)
    return None


def load_entities(session: requests.Session) -> list[tuple[str, str, str]]:
    """Returns (kind, name, path) for every company + artist."""
    out = []
    for kind, path in (("company", "/companies"), ("artist", "/artists")):
        html = fetch(session, BASE + path)
        if not html:
            continue
        seen = set()
        for href, name in INDEX_ENTRY_RE.findall(html):
            if href in seen:
                continue
            seen.add(href)
            out.append((kind, name.strip(), href))
    return out


def scrape_entity_credits(
    session: requests.Session, path: str, page_delay: float = 0.2
) -> list[tuple[int, str, int]]:
    """Returns list of (imdb_id, title, year) for one company/artist, all pages."""
    out = []
    page = 1
    while True:
        url = f"{BASE}{path}" if page == 1 else f"{BASE}{path}?page={page}"
        html = fetch(session, url)
        if not html:
            break
        for imdb_id, title, year in GALLERY_ITEM_RE.findall(html):
            out.append((int(imdb_id), title.strip(), int(year)))
        if not HAS_NEXT_RE.search(html):
            break
        page += 1
        if page > 60:  # sanity cap
            break
        time.sleep(page_delay)
    return out


def build_census_lookup():
    census = list(csv.DictReader(CENSUS.open(encoding="utf-8")))
    id_to_imdb = {}
    if HORROR_MOVIES.exists():
        for r in csv.DictReader(HORROR_MOVIES.open(encoding="utf-8")):
            if r.get("imdb_id"):
                id_to_imdb[r["id"]] = r["imdb_id"]

    by_imdb, by_title_year = {}, {}
    for r in census:
        cid = r["id"]
        imdb = id_to_imdb.get(cid)
        if imdb and imdb.startswith("tt"):
            by_imdb[int(imdb[2:])] = r
        try:
            y = int(float(r["year"]))
        except (TypeError, ValueError):
            continue
        by_title_year[(norm_title(r["title"]), y)] = r
    return by_imdb, by_title_year


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--limit", type=int, default=0, help="process only the first N unprocessed entities"
    )
    ap.add_argument("--rate", type=float, default=6.0)
    args = ap.parse_args()

    session = requests.Session()
    by_imdb, by_title_year = build_census_lookup()
    print(f"census lookup: {len(by_imdb):,} by imdb_id, {len(by_title_year):,} by title+year")

    entities = load_entities(session)
    print(f"directory: {len(entities):,} entities (companies + artists)")

    done = set()
    if ENTITIES_OUT.exists():
        done = {r["path"] for r in csv.DictReader(ENTITIES_OUT.open(encoding="utf-8"))}

    todo = [e for e in entities if e[2] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"already done: {len(done):,} | to process now: {len(todo):,}")
    if not todo:
        print("nothing to do.")
        return

    ent_new = not ENTITIES_OUT.exists()
    ent_f = ENTITIES_OUT.open("a", newline="", encoding="utf-8")
    ent_w = csv.DictWriter(
        ent_f, fieldnames=["kind", "name", "path", "total_credits", "horror_matches"]
    )
    if ent_new:
        ent_w.writeheader()

    cred_new = not CREDITS_OUT.exists()
    cred_f = CREDITS_OUT.open("a", newline="", encoding="utf-8")
    cred_w = csv.DictWriter(
        cred_f,
        fieldnames=[
            "census_id",
            "title",
            "year",
            "credit_kind",
            "credit_name",
            "match_method",
            "imdb_id",
        ],
    )
    if cred_new:
        cred_w.writeheader()

    min_interval = 1.0 / args.rate if args.rate > 0 else 0.0
    for i, (kind, name, path) in enumerate(todo, 1):
        t0 = time.monotonic()
        credits = scrape_entity_credits(session, path)
        matches = {}
        for imdb_id, title, year in credits:
            hit = by_imdb.get(imdb_id)
            method = "imdb_id"
            if not hit:
                hit = by_title_year.get((norm_title(title), year))
                method = "title_year"
            if hit:
                matches[hit["id"]] = (hit, method, imdb_id)  # dedupe multi-version posters
        matches = list(matches.values())

        for hit, method, imdb_id in matches:
            cred_w.writerow(
                {
                    "census_id": hit["id"],
                    "title": hit["title"],
                    "year": hit["year"],
                    "credit_kind": kind,
                    "credit_name": name,
                    "match_method": method,
                    "imdb_id": imdb_id,
                }
            )
        cred_f.flush()

        ent_w.writerow(
            {
                "kind": kind,
                "name": name,
                "path": path,
                "total_credits": len(credits),
                "horror_matches": len(matches),
            }
        )
        ent_f.flush()

        elapsed = time.monotonic() - t0
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        if i % 25 == 0 or i == len(todo):
            print(
                f"  {i}/{len(todo)} entities | last: {name!r} ({kind}) "
                f"{len(credits)} credits, {len(matches)} horror matches",
                flush=True,
            )

    ent_f.close()
    cred_f.close()
    print("\n=== CINEMATERIAL CREDIT MATCH ===")
    print(f"processed this run: {len(todo):,}")
    print(f"entity progress: {ENTITIES_OUT}")
    print(f"credits found: {CREDITS_OUT}")
    print("re-run this command to continue where it left off.")


if __name__ == "__main__":
    main()
