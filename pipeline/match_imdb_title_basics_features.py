#!/usr/bin/env python3
"""Match corpus features missing IMDb ids against IMDb title.basics.

Target set: posters.csv ids with no valid tt… in imdb_ids.csv and
runtime > 40 in horror_movies.csv.

Matching: normalized primaryTitle/originalTitle + startYear (exact, then ±1),
preferring titleType movie/tvMovie; Horror genre used to disambiguate.

Writes:
  data/imdb_basics_match_features_hits.csv
  data/imdb_basics_match_features_ambiguous.csv
  data/imdb_basics_match_features_miss.csv
  data/imdb_ids.csv  (merge accepted)
  data/horror_movies.csv  (imdb_id column if present)

Usage:
  python3 match_imdb_title_basics_features.py
  python3 match_imdb_title_basics_features.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import gzip
import re
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path

from enrich_imdb_ids import (
    DATA,
    HM,
    POSTERS,
    SIDECAR,
    load_sidecar,
    merge_into_horror_movies,
    write_sidecar,
)

BASICS_GZ = DATA / "imdb_datasets" / "title.basics.tsv.gz"
BASICS_URL = "https://datasets.imdbws.com/title.basics.tsv.gz"

HITS_OUT = DATA / "imdb_basics_match_features_hits.csv"
AMBIG_OUT = DATA / "imdb_basics_match_features_ambiguous.csv"
MISS_OUT = DATA / "imdb_basics_match_features_miss.csv"

PREFERRED_TYPES = frozenset({"movie", "tvMovie"})
EXCLUDED_TYPES = frozenset({"short", "tvEpisode", "videoGame"})
FALLBACK_TYPES = frozenset({"video"})  # only if no preferred candidate

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize_title(s: str) -> str:
    """Lowercase, strip accents/punctuation, collapse space, drop leading 'the '."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    if s.startswith("the "):
        s = s[4:].strip()
    return s


def ensure_basics() -> Path:
    if BASICS_GZ.exists() and BASICS_GZ.stat().st_size > 1_000_000:
        return BASICS_GZ
    BASICS_GZ.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {BASICS_URL} → {BASICS_GZ} …")
    urllib.request.urlretrieve(BASICS_URL, BASICS_GZ)
    return BASICS_GZ


def valid_tt(s: str) -> bool:
    s = (s or "").strip()
    return s.startswith("tt") and len(s) > 2 and s[2:].isdigit()


def load_targets(limit: int = 0) -> list[dict]:
    """Corpus posters without tt, runtime > 40."""
    corpus: list[int] = []
    poster_meta: dict[int, dict] = {}
    seen: set[int] = set()
    with POSTERS.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if pid in seen:
                continue
            seen.add(pid)
            corpus.append(pid)
            year = None
            yraw = (r.get("year") or "").strip()
            try:
                year = int(float(yraw))
            except (TypeError, ValueError):
                year = None
            if year == 9999:
                year = None
            poster_meta[pid] = {"title": (r.get("title") or "").strip(), "year": year}

    sidecar = load_sidecar()
    hm: dict[int, dict] = {}
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (TypeError, ValueError):
                continue
            try:
                rt = int(float(r.get("runtime") or 0))
            except (TypeError, ValueError):
                rt = 0
            year = None
            rd = (r.get("release_date") or "")[:4]
            if rd.isdigit():
                year = int(rd)
            hm[pid] = {
                "runtime": rt,
                "title": (r.get("title") or "").strip(),
                "original_title": (r.get("original_title") or "").strip(),
                "year": year,
            }

    out: list[dict] = []
    for pid in corpus:
        if valid_tt(sidecar.get(pid, "")):
            continue
        meta = hm.get(pid)
        if not meta or meta["runtime"] <= 40:
            continue
        pm = poster_meta.get(pid, {})
        title = pm.get("title") or meta["title"]
        year = pm.get("year") if pm.get("year") is not None else meta["year"]
        out.append(
            {
                "id": pid,
                "title": title,
                "original_title": meta["original_title"],
                "year": year,
                "runtime": meta["runtime"],
            }
        )
    if limit:
        out = out[:limit]
    return out


def parse_year(raw: str) -> int | None:
    if not raw or raw == "\\N":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def is_horror(genres: str) -> bool:
    if not genres or genres == "\\N":
        return False
    return "Horror" in genres.split(",")


def scan_basics(
    basics_path: Path, needed_norms: set[str]
) -> dict[str, list[dict]]:
    """Stream title.basics; collect rows whose primary/original norm is needed."""
    by_norm: dict[str, list[dict]] = defaultdict(list)
    n_rows = 0
    with gzip.open(basics_path, "rt", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            n_rows += 1
            if n_rows % 2_000_000 == 0:
                print(f"  … scanned {n_rows:,} title.basics rows")
            ttype = row.get("titleType") or ""
            if ttype in EXCLUDED_TYPES:
                continue
            if ttype not in PREFERRED_TYPES and ttype not in FALLBACK_TYPES:
                continue
            pt = normalize_title(row.get("primaryTitle") or "")
            ot = normalize_title(row.get("originalTitle") or "")
            hit_keys = set()
            if pt and pt in needed_norms:
                hit_keys.add(pt)
            if ot and ot in needed_norms:
                hit_keys.add(ot)
            if not hit_keys:
                continue
            cand = {
                "tconst": row["tconst"],
                "titleType": ttype,
                "primaryTitle": row.get("primaryTitle") or "",
                "originalTitle": row.get("originalTitle") or "",
                "startYear": parse_year(row.get("startYear") or ""),
                "genres": row.get("genres") or "",
                "is_horror": is_horror(row.get("genres") or ""),
            }
            for k in hit_keys:
                by_norm[k].append(cand)
    print(f"  scanned {n_rows:,} rows; {sum(len(v) for v in by_norm.values()):,} candidate hits")
    return by_norm


def filter_by_year(
    cands: list[dict], year: int | None
) -> tuple[list[dict], str]:
    """Return (candidates, year_mode) where year_mode is exact|fuzzy|none|any."""
    if year is None:
        return cands, "any"
    exact = [c for c in cands if c["startYear"] == year]
    if exact:
        return exact, "exact"
    fuzzy = [
        c
        for c in cands
        if c["startYear"] is not None and abs(c["startYear"] - year) == 1
    ]
    if fuzzy:
        return fuzzy, "fuzzy"
    return [], "none"


def prefer_types(cands: list[dict]) -> list[dict]:
    preferred = [c for c in cands if c["titleType"] in PREFERRED_TYPES]
    if preferred:
        return preferred
    return [c for c in cands if c["titleType"] in FALLBACK_TYPES]


def dedupe_tconst(cands: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for c in cands:
        tt = c["tconst"]
        if tt in seen:
            continue
        seen.add(tt)
        out.append(c)
    return out


def match_one(target: dict, by_norm: dict[str, list[dict]]) -> dict:
    """Classify one target: unique / horror_disambiguated / ambiguous / none."""
    pid = target["id"]
    year = target["year"]
    norms: list[str] = []
    for raw in (target["title"], target["original_title"]):
        n = normalize_title(raw)
        if n and n not in norms:
            norms.append(n)

    pooled: list[dict] = []
    for n in norms:
        pooled.extend(by_norm.get(n, []))
    pooled = dedupe_tconst(pooled)

    year_filtered, year_mode = filter_by_year(pooled, year)
    typed = prefer_types(year_filtered)
    typed = dedupe_tconst(typed)

    base = {
        "id": pid,
        "title": target["title"],
        "original_title": target["original_title"],
        "year": year if year is not None else "",
        "candidates": typed,
        "year_mode": year_mode,
    }

    if not typed:
        return {**base, "status": "none", "match_reason": "", "accepted": None}

    if len(typed) == 1:
        c = typed[0]
        reason = "unique"
        if year_mode == "fuzzy":
            reason = "unique_year_fuzzy"
        return {
            **base,
            "status": "unique",
            "match_reason": reason,
            "accepted": c,
        }

    horror_only = [c for c in typed if c["is_horror"]]
    if len(horror_only) == 1:
        c = horror_only[0]
        reason = "horror_disambiguated"
        if year_mode == "fuzzy":
            reason = "horror_disambiguated_year_fuzzy"
        return {
            **base,
            "status": "horror_disambiguated",
            "match_reason": reason,
            "accepted": c,
        }

    return {**base, "status": "ambiguous", "match_reason": "", "accepted": None}


def write_hits(rows: list[dict]) -> None:
    fields = [
        "id",
        "title",
        "year",
        "tconst",
        "titleType",
        "primaryTitle",
        "startYear",
        "match_reason",
    ]
    with HITS_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            c = r["accepted"]
            w.writerow(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "year": r["year"],
                    "tconst": c["tconst"],
                    "titleType": c["titleType"],
                    "primaryTitle": c["primaryTitle"],
                    "startYear": c["startYear"] if c["startYear"] is not None else "",
                    "match_reason": r["match_reason"],
                }
            )


def write_ambiguous(rows: list[dict]) -> None:
    fields = [
        "id",
        "title",
        "year",
        "n_candidates",
        "tconsts",
        "titleTypes",
        "primaryTitles",
        "startYears",
        "genres_list",
        "year_mode",
    ]
    with AMBIG_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            cs = r["candidates"]
            w.writerow(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "year": r["year"],
                    "n_candidates": len(cs),
                    "tconsts": "|".join(c["tconst"] for c in cs),
                    "titleTypes": "|".join(c["titleType"] for c in cs),
                    "primaryTitles": "|".join(c["primaryTitle"] for c in cs),
                    "startYears": "|".join(
                        str(c["startYear"]) if c["startYear"] is not None else ""
                        for c in cs
                    ),
                    "genres_list": "|".join(c["genres"] for c in cs),
                    "year_mode": r["year_mode"],
                }
            )


def write_miss(rows: list[dict]) -> None:
    fields = ["id", "title", "original_title", "year", "year_mode"]
    with MISS_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "original_title": r["original_title"],
                    "year": r["year"],
                    "year_mode": r["year_mode"],
                }
            )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="write report CSVs but do not merge into imdb_ids / HM",
    )
    ap.add_argument(
        "--basics",
        type=Path,
        default=None,
        help="path to title.basics.tsv.gz (default: data/imdb_datasets/)",
    )
    args = ap.parse_args()

    targets = load_targets(limit=args.limit)
    print(f"target features (no tt, runtime>40): {len(targets):,}")

    needed: set[str] = set()
    for t in targets:
        for raw in (t["title"], t["original_title"]):
            n = normalize_title(raw)
            if n:
                needed.add(n)
    print(f"unique normalized title keys: {len(needed):,}")

    basics = args.basics or ensure_basics()
    print(f"scanning {basics} …")
    by_norm = scan_basics(basics, needed)

    results = [match_one(t, by_norm) for t in targets]
    hits = [r for r in results if r["status"] in ("unique", "horror_disambiguated")]
    unique = [r for r in results if r["status"] == "unique"]
    horror_dis = [r for r in results if r["status"] == "horror_disambiguated"]
    ambig = [r for r in results if r["status"] == "ambiguous"]
    miss = [r for r in results if r["status"] == "none"]

    write_hits(hits)
    write_ambiguous(ambig)
    write_miss(miss)

    print()
    print("=== results ===")
    print(f"  unique accepted:          {len(unique):,}")
    print(f"  horror_disambiguated:     {len(horror_dis):,}")
    print(f"  accepted total:           {len(hits):,}")
    print(f"  ambiguous:                {len(ambig):,}")
    print(f"  miss:                     {len(miss):,}")
    print(f"  → {HITS_OUT.name}")
    print(f"  → {AMBIG_OUT.name}")
    print(f"  → {MISS_OUT.name}")

    if hits:
        print("\nsample hits:")
        for r in hits[:12]:
            c = r["accepted"]
            print(
                f"  {r['id']:>8}  {r['title'][:40]:<40}  "
                f"{r['year']} → {c['tconst']} ({r['match_reason']})"
            )

    if args.dry_run:
        print("\n(--dry-run: skipping imdb_ids / HM merge)")
        remaining = len(targets) - len(hits)
        print(f"would leave {remaining:,} features without tt")
        return

    sidecar = load_sidecar()
    accepted_map: dict[int, str] = {}
    for r in hits:
        pid = int(r["id"])
        tt = r["accepted"]["tconst"]
        accepted_map[pid] = tt
        sidecar[pid] = tt

    write_sidecar(sidecar)
    print(f"\nmerged {len(accepted_map):,} tt into {SIDECAR}")

    if HM.exists():
        # merge only accepted into HM without wiping other imdb_ids:
        # merge_into_horror_movies uses mapping.get(pid) or existing — pass full sidecar
        merge_into_horror_movies(sidecar)

    remaining = 0
    with POSTERS.open(encoding="utf-8", errors="replace") as f:
        poster_ids = []
        seen: set[int] = set()
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (TypeError, ValueError):
                continue
            if pid not in seen:
                seen.add(pid)
                poster_ids.append(pid)
    runtime: dict[int, int] = {}
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
                runtime[pid] = int(float(r.get("runtime") or 0))
            except (TypeError, ValueError):
                continue
    for pid in poster_ids:
        if valid_tt(sidecar.get(pid, "")):
            continue
        if runtime.get(pid, 0) > 40:
            remaining += 1
    print(f"remaining features without tt (runtime>40): {remaining:,}")


if __name__ == "__main__":
    main()
