#!/usr/bin/env python3
"""Safe IMDb suggest match for corpus features missing tt…

Target: data/imdb_basics_match_features_miss.csv plus unresolved rows from
data/imdb_basics_ambiguous_selenium_miss.csv. Skips any id that already has
a valid tt in imdb_ids.csv.

Matching (strict):
  - suggestion API title (``l``) casefold-equals corpus title or original_title
  - year must match exactly
  - only qid movie/tvMovie (or q feature)
  - accept only when a single winner remains
  Year ±1 + director confirmation is handled by enrich_imdb_selenium_features.py.

Writes:
  data/imdb_suggest_features_hits.csv
  data/imdb_suggest_features_miss.csv
  data/imdb_ids.csv  (merge accepted)

Usage:
  python3 match_imdb_suggest_features.py
  python3 match_imdb_suggest_features.py --limit 20 --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
import urllib.parse
from pathlib import Path

import requests

from enrich_imdb_ids import DATA, SIDECAR, load_sidecar, write_sidecar
from match_imdb_title_basics_features import valid_tt

MISS_IN = DATA / "imdb_basics_match_features_miss.csv"
AMBIG_MISS_IN = DATA / "imdb_basics_ambiguous_selenium_miss.csv"
HITS_OUT = DATA / "imdb_suggest_features_hits.csv"
MISS_OUT = DATA / "imdb_suggest_features_miss.csv"

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
API_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.imdb.com",
    "Referer": "https://www.imdb.com/",
}

PREFERRED_QID = frozenset({"movie", "tvMovie"})
PREFERRED_Q = frozenset({"feature", "TV movie"})
DEPRIORITIZED_QID = frozenset({"short", "tvEpisode", "tvSeries", "videoGame", "podcastSeries", "musicVideo"})

HIT_FIELDS = [
    "id",
    "imdb_id",
    "title",
    "original_title",
    "year",
    "imdb_title",
    "imdb_year",
    "qid",
    "year_delta",
    "match",
]
MISS_FIELDS = ["id", "title", "original_title", "year", "reason", "n_candidates"]


def is_preferred(item: dict) -> bool:
    qid = (item.get("qid") or "").strip()
    q = (item.get("q") or "").strip()
    if qid in PREFERRED_QID or q in PREFERRED_Q:
        return True
    if qid in DEPRIORITIZED_QID:
        return False
    # video / tvMovie / unknown — keep as secondary
    return False


def suggest_title(session: requests.Session, title: str) -> list[dict]:
    key = title.strip().lower()
    if not key:
        return []
    first = key[0] if key[0].isalnum() else "0"
    url = (
        f"https://v2.sg.media-imdb.com/suggestion/"
        f"{first}/{urllib.parse.quote(key)}.json"
    )
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            r = session.get(url, headers=API_HEADERS, timeout=30)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 + attempt * 1.5)
                continue
            r.raise_for_status()
            return list(r.json().get("d") or [])
        except Exception as e:
            last_err = e
            time.sleep(1.0 + attempt * 1.2)
    if last_err:
        raise last_err
    return []


def parse_year(raw) -> int | None:
    try:
        y = int(raw)
    except (TypeError, ValueError):
        return None
    if 1888 <= y <= 2035:
        return y
    return None


def title_matches(item_title: str, titles: list[str]) -> bool:
    """Strict casefold equality only (no 'the '-stripping normalize)."""
    it = (item_title or "").casefold().strip()
    if not it:
        return False
    return any(it == t.casefold().strip() for t in titles if t and t.strip())


def safe_match(
    titles: list[str], year: int, items: list[dict]
) -> tuple[dict | None, str, int]:
    """Return (winner, reason_if_none, n_title_year_cands).

    Only movie/feature + exact year. Year ±1 is left to Selenium+director.
    """
    pool: list[dict] = []
    for x in items:
        tt = str(x.get("id") or "")
        if not tt.startswith("tt"):
            continue
        if not title_matches(str(x.get("l") or ""), titles):
            continue
        yi = parse_year(x.get("y"))
        if yi is None or yi != year:
            continue
        cand = {
            "imdb_id": tt,
            "imdb_title": str(x.get("l") or ""),
            "imdb_year": yi,
            "year_delta": 0,
            "qid": (x.get("qid") or "").strip(),
            "q": (x.get("q") or "").strip(),
            "raw": x,
        }
        if not is_preferred(cand):
            continue
        pool.append(cand)

    if not pool:
        return None, "no_title_year_match", 0

    by_tt: dict[str, dict] = {}
    for c in pool:
        by_tt[c["imdb_id"]] = c
    pool = list(by_tt.values())

    if len(pool) == 1:
        return pool[0], "movie_exact_year", 1

    return None, f"ambiguous_n={len(pool)}", len(pool)


def load_input_rows() -> list[dict]:
    rows: list[dict] = []
    seen: set[int] = set()

    def add_from(path: Path, *, has_original: bool) -> None:
        if not path.exists():
            return
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if pid in seen:
                    continue
                seen.add(pid)
                year = parse_year(r.get("year"))
                rows.append(
                    {
                        "id": pid,
                        "title": (r.get("title") or "").strip(),
                        "original_title": (
                            (r.get("original_title") or "").strip()
                            if has_original
                            else ""
                        ),
                        "year": year,
                    }
                )

    add_from(MISS_IN, has_original=True)
    add_from(AMBIG_MISS_IN, has_original=False)
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--jitter", type=float, default=0.2)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="do not merge hits into imdb_ids.csv",
    )
    ap.add_argument(
        "--no-merge",
        action="store_true",
        help="alias of --dry-run for merge skip",
    )
    args = ap.parse_args()
    no_merge = args.dry_run or args.no_merge

    mapping = load_sidecar()
    raw = load_input_rows()
    todo: list[dict] = []
    skipped_has_tt = 0
    skipped_no_year = 0
    for r in raw:
        if valid_tt(mapping.get(r["id"], "")):
            skipped_has_tt += 1
            continue
        if r["year"] is None:
            skipped_no_year += 1
            todo.append({**r, "_skip": "no_year"})
            continue
        if not (r["title"] or r["original_title"]):
            skipped_no_year += 1
            todo.append({**r, "_skip": "no_title"})
            continue
        todo.append(r)

    processable = [r for r in todo if not r.get("_skip")]
    if args.limit:
        processable = processable[: args.limit]
        # keep only early skips that aren't in the limited set? report from processable
        todo = processable

    print(
        f"input={len(raw)} skip_has_tt={skipped_has_tt} "
        f"to_query={len(processable)} (pre-skip no_year/title in run)",
        flush=True,
    )

    session = requests.Session()
    session.trust_env = False
    session.headers.update(API_HEADERS)

    hits: list[dict] = []
    misses: list[dict] = []

    # rows with skip flags first
    for r in todo:
        if r.get("_skip"):
            misses.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "original_title": r.get("original_title") or "",
                    "year": r.get("year") or "",
                    "reason": r["_skip"],
                    "n_candidates": 0,
                }
            )

    n = len(processable)
    for i, row in enumerate(processable, 1):
        pid = row["id"]
        title = row["title"]
        ot = row.get("original_title") or ""
        year = int(row["year"])
        titles = []
        for t in (title, ot):
            t = (t or "").strip()
            if t and t not in titles:
                titles.append(t)

        items: list[dict] = []
        seen_tt: set[str] = set()
        err = None
        for q in titles:
            try:
                for x in suggest_title(session, q):
                    tt = str(x.get("id") or "")
                    if tt in seen_tt:
                        continue
                    seen_tt.add(tt)
                    items.append(x)
            except Exception as e:
                err = f"suggest_err {type(e).__name__}"
                break
            if len(titles) > 1:
                time.sleep(0.15)

        if err:
            misses.append(
                {
                    "id": pid,
                    "title": title,
                    "original_title": ot,
                    "year": year,
                    "reason": err,
                    "n_candidates": 0,
                }
            )
            print(f"  {i}/{n} ERR {pid} {err}", flush=True)
            time.sleep(args.delay + random.uniform(0, args.jitter))
            continue

        winner, reason, n_cands = safe_match(titles, year, items)
        if not winner:
            misses.append(
                {
                    "id": pid,
                    "title": title,
                    "original_title": ot,
                    "year": year,
                    "reason": reason,
                    "n_candidates": n_cands,
                }
            )
            if i % 25 == 0 or i == n or reason.startswith("ambiguous"):
                print(
                    f"  {i}/{n} MISS {pid} {title!r} {year} {reason}",
                    flush=True,
                )
        else:
            hit = {
                "id": pid,
                "imdb_id": winner["imdb_id"],
                "title": title,
                "original_title": ot,
                "year": year,
                "imdb_title": winner["imdb_title"],
                "imdb_year": winner["imdb_year"],
                "qid": winner["qid"] or winner.get("q") or "",
                "year_delta": winner["year_delta"],
                "match": reason,
            }
            hits.append(hit)
            mapping[pid] = winner["imdb_id"]
            print(
                f"  {i}/{n} OK {pid} {winner['imdb_id']} {title!r} "
                f"({reason} Δ={winner['year_delta']})",
                flush=True,
            )

        if i % 40 == 0:
            write_csv(HITS_OUT, hits, HIT_FIELDS)
            write_csv(MISS_OUT, misses, MISS_FIELDS)
            if hits and not no_merge:
                write_sidecar(mapping)

        time.sleep(args.delay + random.uniform(0, args.jitter))

    write_csv(HITS_OUT, hits, HIT_FIELDS)
    write_csv(MISS_OUT, misses, MISS_FIELDS)
    if hits and not no_merge:
        write_sidecar(mapping)
        print(f"Merged {len(hits)} hits into {SIDECAR}")

    reasons: dict[str, int] = {}
    for m in misses:
        key = str(m["reason"])
        if key.startswith("ambiguous_n="):
            key = "ambiguous"
        reasons[key] = reasons.get(key, 0) + 1

    print(
        f"\n=== SUGGEST FEATURES PASS ===\n"
        f"hits={len(hits)} miss={len(misses)}\n"
        f"miss reasons: {json.dumps(reasons, ensure_ascii=False)}\n"
        f"→ {HITS_OUT.name} / {MISS_OUT.name}"
    )


if __name__ == "__main__":
    main()
