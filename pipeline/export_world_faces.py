#!/usr/bin/env python3
"""Faces on horror posters by original language -> site/data/world.js.

The published corpus is English-language only (canonical_ids.txt). The
non-English horror films it excludes (data/excluded_non_english.csv) went
through the same measuring pipeline, so this compares them on the one measure
the essay tracks for faces: share of posters with at least one YuNet face
(faces_v2.csv n_faces > 0).

Non-English films get the corpus's other filters from the TMDB cache
(fetch_tmdb_details.py): released, not adult, no Animation / Music / TV Movie,
release year 1900–2026, a poster, and no other exclusion list.

  python3 export_world_faces.py

Writes site/data/world.js:
  WORLD_FACES  2000–2026, languages with >= MIN_N posters:
               [{lang, n, face, lo, hi}] (shares 0-100, Wilson 95% interval)
  FACE_ERAS    {lang: [[era, n, face]]} for the languages the copy cites
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE.parent / "site" / "data" / "world.js"
TMDB = DATA / "qa" / "tmdb_details" / "tmdb_details.jsonl"
MIN_N = 150
RECENT = (2000, 2026)
ERAS = [
    ("<1980", 1900, 1979),
    ("1980–99", 1980, 1999),
    ("2000–09", 2000, 2009),
    ("2010–26", 2010, 2026),
]
ERA_LANGS = ["en", "ja", "es"]
EXCLUDED_GENRES = {"Animation", "Music", "TV Movie"}
# TMDB tags some Chinese-language films "cn" (Cantonese) and others "zh".
LANG_ALIAS = {"cn": "zh"}


def read_ids(path: Path, col: str = "id") -> set[int]:
    with path.open(newline="", encoding="utf-8") as f:
        return {int(r[col]) for r in csv.DictReader(f)}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return mid - half, mid + half


def comparable_non_english() -> dict[int, str]:
    """Excluded non-English films that pass every other corpus filter."""
    details = {}
    for line in TMDB.open(encoding="utf-8"):
        rec = json.loads(line)
        details[int(rec["id"])] = rec
    other: set[int] = set()
    for path in DATA.glob("excluded_*.csv"):
        if path.name == "excluded_non_english.csv" or path.name.endswith("_review.csv"):
            continue
        other |= read_ids(path)
    out = {}
    with (DATA / "excluded_non_english.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = int(r["id"])
            d = details.get(pid)
            if not d or d.get("http") != 200 or pid in other:
                continue
            year = (d.get("release_date") or "")[:4]
            if (
                d.get("status") != "Released"
                or d.get("adult")
                or EXCLUDED_GENRES & set(d.get("genres") or [])
                or not year.isdigit()
                or not 1900 <= int(year) <= 2026
                or not d.get("poster_path")
            ):
                continue
            lang = r["original_language"]
            out[pid] = LANG_ALIAS.get(lang, lang)
    return out


def main() -> None:
    canon = (DATA / "canonical_ids.txt").read_text(encoding="utf-8").split()
    langs = {int(pid): "en" for pid in canon}
    langs.update(comparable_non_english())
    faces: dict[int, tuple[int, bool]] = {}
    with (DATA / "faces_v2.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = int(r["id"])
            if pid in langs and r["year"]:
                faces[pid] = (int(float(r["year"])), float(r["n_faces"] or 0) > 0)

    def share(rows: list[bool]) -> tuple[int, float, float, float]:
        n, k = len(rows), sum(rows)
        lo, hi = wilson(k, n)
        return n, 100 * k / n, 100 * lo, 100 * hi

    by_lang: dict[str, list[bool]] = {}
    for pid, (year, has) in faces.items():
        if RECENT[0] <= year <= RECENT[1]:
            by_lang.setdefault(langs[pid], []).append(has)
    world = []
    for lang, rows in by_lang.items():
        if len(rows) >= MIN_N:
            n, face, lo, hi = share(rows)
            world.append(
                {
                    "lang": lang,
                    "n": n,
                    "face": round(face, 1),
                    "lo": round(lo, 1),
                    "hi": round(hi, 1),
                }
            )
    world.sort(key=lambda r: -r["face"])

    eras = {}
    for lang in ERA_LANGS:
        eras[lang] = []
        for name, y0, y1 in ERAS:
            rows = [
                has for pid, (year, has) in faces.items() if langs[pid] == lang and y0 <= year <= y1
            ]
            if rows:
                n, face, _, _ = share(rows)
                eras[lang].append([name, n, round(face, 1)])

    n_other = sum(r["n"] for r in world if r["lang"] != "en")
    OUT.write_text(
        f"/* Faces by original language, {RECENT[0]}–{RECENT[1]} — pipeline/export_world_faces.py */\n"
        f"window.WORLD_FACES={json.dumps(world, ensure_ascii=False, separators=(',', ':'))};\n"
        f"window.FACE_ERAS={json.dumps(eras, ensure_ascii=False, separators=(',', ':'))};\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT}: {len(world)} languages, {n_other:,} non-English posters")
    for r in world:
        print(f"  {r['lang']:3s} n={r['n']:6,} face={r['face']:5.1f}% ({r['lo']}–{r['hi']})")


if __name__ == "__main__":
    main()
