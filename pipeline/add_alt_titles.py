#!/usr/bin/env python3
"""Add alternative-titles columns to data/master_dataset.csv, for every poster
that has a known IMDb id -- not just the drift-review suspects. Lets future QA
(title-match, language checks, etc.) reference AKAs directly from the master
table instead of re-fetching per case.

Sources:
  - IMDb title.akas.tsv.gz (data/imdb_datasets/, ~58.6M rows) -- full AKA list
    per tconst, one streaming pass, only keeping rows whose tconst is one of
    ours.
  - TMDB alternative_titles cache (data/qa/tmdb_alt_titles_cache.json) --
    ALREADY FETCHED for the 547 Nova-drift mismatch candidates only (see
    check_alt_titles_vs_drift.py). Not full-corpus coverage; merged in as-is,
    with alt_titles_tmdb_coverage flagging which rows actually have it.

id -> imdb_id mapping: union of data/imdb_ids*.csv (104,150 / 145,492 have one
-- community/genre-expansion ids without an imdb_id get no IMDb AKAs, only
whatever TMDB cache already covers).

  python3 add_alt_titles.py

Adds columns: alt_titles_imdb, n_alt_titles_imdb, alt_titles_tmdb,
n_alt_titles_tmdb, imdb_id (if not already present).
Rewrites data/master_dataset.csv in place (backs up the previous version).
"""

from __future__ import annotations

import csv
import gzip
import json
import shutil
from pathlib import Path

DATA = Path(__file__).parent / "data"
MASTER = DATA / "master_dataset.csv"
AKAS_GZ = DATA / "imdb_datasets" / "title.akas.tsv.gz"
TMDB_CACHE = DATA / "qa" / "tmdb_alt_titles_cache.json"

IMDB_ID_SOURCES = [
    "imdb_ids.csv",
    "imdb_ids_scifi.csv",
    "imdb_ids_mystery.csv",
    "imdb_ids_thriller.csv",
    "imdb_ids_wikidata.csv",
]

PREFERRED_REGIONS = {"US", "GB", "\\N"}


def load_id_to_imdb() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for fname in IMDB_ID_SOURCES:
        path = DATA / fname
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                iid = (row.get("imdb_id") or "").strip()
                if iid:
                    mapping[row["id"]] = iid
    return mapping


def scan_akas_for_tconsts(tconsts: set[str]) -> dict[str, list[str]]:
    """One streaming pass over title.akas.tsv.gz; collect distinct AKA titles
    per tconst, preferring US/GB/worldwide rows first but keeping everything."""
    out: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    n = 0
    with gzip.open(AKAS_GZ, "rt", encoding="utf-8", errors="replace") as f:
        # skip the header: titleId ordering title region language types attributes isOriginalTitle
        f.readline()
        for line in f:
            n += 1
            if n % 10_000_000 == 0:
                print(
                    f"  … akas scanned {n:,} rows ({sum(len(v) for v in out.values()):,} akas kept)"
                )
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 8:
                continue
            tconst, _ordering, title, region, _lang, _types, _attrs, is_original = parts
            if tconst not in tconsts:
                continue
            if is_original == "1":
                continue  # skip the original title itself, we already have it
            title = title.strip()
            if not title:
                continue
            s = seen.setdefault(tconst, set())
            if title.casefold() in s:
                continue
            s.add(title.casefold())
            out.setdefault(tconst, []).append(title if region in PREFERRED_REGIONS else title)
    print(f"  akas done: {n:,} rows scanned, {len(out):,} tconsts with >=1 AKA")
    return out


def main():
    if not AKAS_GZ.exists():
        raise SystemExit(f"missing {AKAS_GZ}")
    if not MASTER.exists():
        raise SystemExit(f"missing {MASTER} -- run build_master_dataset.py first")

    id_to_imdb = load_id_to_imdb()
    print(f"id -> imdb_id mapping: {len(id_to_imdb):,} ids")

    tconsts = set(id_to_imdb.values())
    print(f"unique tconsts a buscar: {len(tconsts):,}")
    print(f"scanning {AKAS_GZ} …")
    akas_by_tconst = scan_akas_for_tconsts(tconsts)

    tmdb_cache: dict[str, list[str]] = {}
    if TMDB_CACHE.exists():
        tmdb_cache = json.loads(TMDB_CACHE.read_text())
    print(
        f"TMDB alt-titles cache: {len(tmdb_cache):,} ids (partial coverage -- only Nova-drift candidates so far)"
    )

    backup = MASTER.with_suffix(".csv.bak_before_alt_titles")
    shutil.copy(MASTER, backup)
    print(f"backup -> {backup}")

    with MASTER.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames)

    new_cols = [
        "imdb_id",
        "alt_titles_imdb",
        "n_alt_titles_imdb",
        "alt_titles_tmdb",
        "n_alt_titles_tmdb",
    ]
    for c in new_cols:
        if c not in fieldnames:
            fieldnames.append(c)

    n_with_imdb_akas = 0
    n_with_tmdb_alts = 0
    for row in rows:
        i = row["id"]
        imdb_id = id_to_imdb.get(i, row.get("imdb_id", ""))
        row["imdb_id"] = imdb_id
        akas = akas_by_tconst.get(imdb_id, []) if imdb_id else []
        row["alt_titles_imdb"] = " | ".join(akas)
        row["n_alt_titles_imdb"] = len(akas)
        if akas:
            n_with_imdb_akas += 1
        tmdb_alts = tmdb_cache.get(i, [])
        row["alt_titles_tmdb"] = " | ".join(tmdb_alts)
        row["n_alt_titles_tmdb"] = len(tmdb_alts)
        if tmdb_alts:
            n_with_tmdb_alts += 1

    with MASTER.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\nEscrito {MASTER} ({len(rows):,} filas, {len(fieldnames)} columnas)")
    print(f"ids con >=1 AKA de IMDb: {n_with_imdb_akas:,}")
    print(
        f"ids con >=1 alt title de TMDB (cobertura parcial, solo Nova-drift): {n_with_tmdb_alts:,}"
    )


if __name__ == "__main__":
    main()
