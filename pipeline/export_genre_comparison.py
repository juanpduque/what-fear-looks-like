#!/usr/bin/env python3
"""Horror against sci-fi, mystery and thriller posters -> site/data/genres.js.

The three other genres went through the same measuring pipeline
(posters_{genre}.csv, faces_v2_{genre}.csv, attributes_{genre}.csv). Horror is
the published corpus (canonical_ids.txt). The other genres get the corpus's
filters from the TMDB cache (fetch_tmdb_details.py --cache
tmdb_details_genres.jsonl): current TMDB genres include the genre and not
Horror, English original language, released, not adult, no Animation / Music /
TV Movie, no exclusion list, year 1900–2026, a poster. A film tagged with two
of the three genres counts in both.

Same measures as the essay: dark = near-black pixel share (Part II), face =
share of posters with at least one YuNet face (Part IV), text = MSER text-like
coverage (Part V).

  python3 export_genre_comparison.py

Writes site/data/genres.js:
  GENRES  {genre: {n, decades: [[decade, n, dark, face, text]]}}
          decades with >= MIN_N posters, shares 0-100
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE.parent / "site" / "data" / "genres.js"
TMDB = DATA / "qa" / "tmdb_details" / "tmdb_details_genres.jsonl"
MIN_N = 100
FIRST_DECADE = 1930
LAST_YEAR = 2026
CUTOFF = "2026-10-08"  # same release cutoff as docs/CORPUS.md
GENRES = {"scifi": "Science Fiction", "mystery": "Mystery", "thriller": "Thriller"}
EXCLUDED_GENRES = {"Animation", "Music", "TV Movie", "Horror"}


def read_ids(path: Path) -> set[int]:
    with path.open(newline="", encoding="utf-8") as f:
        return {int(r["id"]) for r in csv.DictReader(f)}


def comparable(tmdb_genre: str, ids: set[int], details: dict, excluded: set[int]) -> set[int]:
    out = set()
    for pid in ids:
        d = details.get(pid)
        if not d or d.get("http") != 200 or pid in excluded:
            continue
        genres = set(d.get("genres") or [])
        if (
            tmdb_genre not in genres
            or EXCLUDED_GENRES & genres
            or d.get("original_language") != "en"
            or d.get("status") != "Released"
            or (d.get("release_date") or "9999") > CUTOFF
            or d.get("adult")
            or not d.get("poster_path")
        ):
            continue
        out.add(pid)
    return out


def measures(suffix: str, keep: set[int]) -> dict[int, list]:
    """{id: [year, dark, has_face, text]} for ids in keep with all three measures."""
    rows: dict[int, list] = {}
    with (DATA / f"posters{suffix}.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = int(r["id"])
            if pid in keep and pid not in rows:
                rows[pid] = [int(float(r["year"])), float(r["dark_share"]), None, None]
    with (DATA / f"faces_v2{suffix}.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = int(r["id"])
            if pid in rows and rows[pid][2] is None:
                rows[pid][2] = int(float(r["n_faces"])) > 0
    with (DATA / f"attributes{suffix}.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = int(r["id"])
            if pid in rows and rows[pid][3] is None and r["text_area"]:
                rows[pid][3] = float(r["text_area"])
    return {
        pid: v
        for pid, v in rows.items()
        if v[2] is not None and v[3] is not None and 1900 <= v[0] <= LAST_YEAR
    }


def by_decade(rows: dict[int, list]) -> list[list]:
    groups: dict[int, list] = {}
    for year, dark, face, text in rows.values():
        if year >= FIRST_DECADE:
            groups.setdefault(year // 10 * 10, []).append((dark, face, text))
    out = []
    for dec in sorted(groups):
        g = groups[dec]
        n = len(g)
        if n < MIN_N:
            continue
        out.append(
            [
                dec,
                n,
                round(100 * sum(x[0] for x in g) / n, 1),
                round(100 * sum(x[1] for x in g) / n, 1),
                round(100 * sum(x[2] for x in g) / n, 1),
            ]
        )
    return out


def main() -> None:
    details = {}
    for line in TMDB.open(encoding="utf-8"):
        rec = json.loads(line)
        details[int(rec["id"])] = rec
    excluded: set[int] = set()
    for path in DATA.glob("excluded_*.csv"):
        if not path.name.endswith("_review.csv"):
            excluded |= read_ids(path)

    canon = {int(x) for x in (DATA / "canonical_ids.txt").read_text().split() if x.isdigit()}
    result = {"horror": measures("", canon)}
    for key, tmdb_genre in GENRES.items():
        ids = read_ids(DATA / f"posters_{key}.csv")
        result[key] = measures(f"_{key}", comparable(tmdb_genre, ids, details, excluded))

    out = {g: {"n": len(rows), "decades": by_decade(rows)} for g, rows in result.items()}
    OUT.write_text(
        "/* Horror vs sci-fi, mystery, thriller by decade — pipeline/export_genre_comparison.py */\n"
        f"window.GENRES={json.dumps(out, separators=(',', ':'))};\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT}")
    for g, v in out.items():
        last = v["decades"][-1]
        print(
            f"  {g:8s} n={v['n']:6,}  {last[0]}s n={last[1]:,} "
            f"dark={last[2]}% face={last[3]}% text={last[4]}%"
        )


if __name__ == "__main__":
    main()
