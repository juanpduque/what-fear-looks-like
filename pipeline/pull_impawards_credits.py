#!/usr/bin/env python3
"""Match horror corpus titles against impawards.com and pull poster designer credits.

Reads data/census.csv (id, title, year) and, for each movie, guesses the
impawards.com URL (/<year>/<slug>.html, trying year-1/year+1 as fallback for
release-date drift between databases). When a page matches, extracts the
"Poster design by X" credit (when known) and the full-size poster image URL(s).

Resumable: re-running skips ids already present in the output CSV, so the
job can be stopped (closed laptop, etc.) and continued later in batches.

  python3 pull_impawards_credits.py --limit 200          # sample test run
  python3 pull_impawards_credits.py --workers 6          # continue full run
  python3 pull_impawards_credits.py --rate 6              # max requests/sec
"""
from __future__ import annotations

import argparse
import csv
import re
import threading
import time
import unicodedata
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
INPUT = DATA / "census.csv"
OUTPUT = DATA / "impawards_credits.csv"
BASE = "http://www.impawards.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PulpAnalytics-AnatomyOfFear/1.0; +personal research)",
}
FIELDNAMES = [
    "id", "title", "year", "status", "matched_year", "impawards_url",
    "poster_designer", "poster_illustrator", "poster_image_urls",
]

TITLE_YEAR_RE = re.compile(r">\s*([^<>]{1,150}?)\s*\((\d{4})\)\s*<")
# credit text is usually wrapped in a link: `Poster design by <a href=...>Name</a>`
DESIGN_RE = re.compile(r"Poster design by\s*:?\s*(?:<a[^>]*>)?([^<]{1,100})", re.IGNORECASE)
ILLUSTRATION_RE = re.compile(r"Poster illustration by\s*:?\s*(?:<a[^>]*>)?([^<]{1,100})", re.IGNORECASE)
POSTER_JPG_RE = re.compile(r'(?:href|src)\s*=\s*"?posters/([a-z0-9_]+\.jpg)', re.IGNORECASE)


NUMERAL_WORDS = {
    "2": "two", "3": "three", "4": "four", "5": "five",
    "6": "six", "7": "seven", "8": "eight", "9": "nine",
}
LEADING_ARTICLE_RE = re.compile(r"^(the|a|an)_")
TRAILING_DIGIT_RE = re.compile(r"_(\d)$")


def slugify(title: str) -> str:
    t = unicodedata.normalize("NFKD", title or "")
    t = t.encode("ascii", "ignore").decode("ascii")
    t = t.lower()
    t = t.replace("'", "").replace("’", "")
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t


def slug_variants(title: str) -> list[str]:
    """impawards.com slugs drop leading articles and sometimes spell out
    trailing digits ("Jaws 2" -> jaws_two.html), so try the plausible forms."""
    base = slugify(title)
    variants = [base]
    no_article = LEADING_ARTICLE_RE.sub("", base)
    if no_article and no_article != base:
        variants.append(no_article)
    for v in list(variants):
        m = TRAILING_DIGIT_RE.search(v)
        if m and m.group(1) in NUMERAL_WORDS:
            variants.append(TRAILING_DIGIT_RE.sub("_" + NUMERAL_WORDS[m.group(1)], v))
    seen, out = set(), []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def norm_compare(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


class RateLimiter:
    def __init__(self, per_second: float):
        self.min_interval = 1.0 / per_second if per_second > 0 else 0.0
        self.lock = threading.Lock()
        self.next_ok = 0.0

    def wait(self):
        if self.min_interval <= 0:
            return
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_ok)
            self.next_ok = start + self.min_interval
        delay = start - now
        if delay > 0:
            time.sleep(delay)


def fetch(session: requests.Session, limiter: RateLimiter, url: str):
    limiter.wait()
    try:
        r = session.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return r.text
        return None
    except requests.RequestException:
        return None


def match_one(session: requests.Session, limiter: RateLimiter, mid: str, title: str, year: str, year_tol: int):
    slugs = slug_variants(title)
    if not slugs:
        return {"id": mid, "title": title, "year": year, "status": "no_slug",
                "matched_year": "", "impawards_url": "", "poster_designer": "", "poster_image_urls": ""}

    try:
        base_year = int(float(year))
    except (TypeError, ValueError):
        base_year = None

    offsets = [0] + [d for i in range(1, year_tol + 1) for d in (i, -i)] if base_year else [0]
    tried_no_page = False

    for off in offsets:
        y = (base_year + off) if base_year is not None else None
        for slug in slugs:
            for path in (slug, f"{slug}_ver1"):
                url = f"{BASE}/{y}/{path}.html" if y else f"{BASE}/{path}.html"
                html = fetch(session, limiter, url)
                if html is None:
                    tried_no_page = True
                    continue

                m = TITLE_YEAR_RE.search(html)
                page_year = m.group(2) if m else ""
                page_title = m.group(1) if m else ""
                if page_title and norm_compare(page_title) != norm_compare(title):
                    continue  # slug collision with a different film
                if page_year and base_year is not None and abs(int(page_year) - base_year) > year_tol:
                    continue

                dm = DESIGN_RE.search(html)
                im = ILLUSTRATION_RE.search(html)
                designer = dm.group(1).strip() if dm else ""
                illustrator = im.group(1).strip() if im else ""
                poster_year = page_year or (str(y) if y else "")
                posters = sorted({f"{BASE}/{poster_year}/posters/{fn}" for fn in POSTER_JPG_RE.findall(html)})
                return {
                    "id": mid, "title": title, "year": year, "status": "matched",
                    "matched_year": page_year or (str(y) if y else ""),
                    "impawards_url": url, "poster_designer": designer,
                    "poster_illustrator": illustrator,
                    "poster_image_urls": "|".join(posters),
                }

    status = "no_page" if tried_no_page else "no_slug"
    return {"id": mid, "title": title, "year": year, "status": status,
            "matched_year": "", "impawards_url": "", "poster_designer": "", "poster_image_urls": ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(INPUT))
    ap.add_argument("--output", default=str(OUTPUT))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--rate", type=float, default=6.0, help="max requests/sec across all workers")
    ap.add_argument("--year-tolerance", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="process only the first N unprocessed rows")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    if not in_path.exists():
        raise SystemExit(f"missing {in_path}")

    rows = list(csv.DictReader(in_path.open(encoding="utf-8")))
    seen = {}
    if out_path.exists():
        for r in csv.DictReader(out_path.open(encoding="utf-8")):
            seen[r["id"]] = r

    todo = [r for r in rows if r["id"] not in seen]
    if args.limit:
        todo = todo[: args.limit]

    print(f"total in corpus: {len(rows):,} | already done: {len(seen):,} | to process now: {len(todo):,}")
    if not todo:
        print("nothing to do.")
        return

    new_file = not out_path.exists()
    out_f = out_path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_f, fieldnames=FIELDNAMES)
    if new_file:
        writer.writeheader()

    session = requests.Session()
    limiter = RateLimiter(args.rate)
    lock = threading.Lock()
    counts = {"matched": 0, "no_page": 0, "no_slug": 0}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def work(r):
        return match_one(session, limiter, r["id"], r["title"], r["year"], args.year_tolerance)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, r): r for r in todo}
        done = 0
        for fut in as_completed(futs):
            result = fut.result()
            with lock:
                writer.writerow(result)
                out_f.flush()
                counts[result["status"]] = counts.get(result["status"], 0) + 1
                done += 1
                if done % 50 == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)} matched={counts.get('matched',0)} "
                          f"no_page={counts.get('no_page',0)} no_slug={counts.get('no_slug',0)}", flush=True)

    out_f.close()
    print(f"\n=== IMPAWARDS CREDIT MATCH ===")
    print(f"processed this run: {len(todo):,}")
    for k, v in counts.items():
        print(f"  {k}: {v:,}")
    print(f"output: {out_path}")
    print(f"re-run this command to continue where it left off.")


if __name__ == "__main__":
    main()
