#!/usr/bin/env python3
"""Share of horror posters that show a recognized star from the film's own cast.

Rekognition RecognizeCelebrities ran on every corpus poster with a YuNet face
(celebrities.csv). A name counts only when it is in the film's TMDB cast
(data/qa/celebrity_cast_verification.csv, cast_match), so look-alike matches
drop out. It is a floor: lesser-known actors are not recognized.

Reported by period for the whole corpus and for films with MIN_VOTES+ TMDB
votes, since the corpus fills up with small films whose casts no model knows.
Source of the late-'90s star sentence and the STARS note in the faces section.

  python3 star_share.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from corpus import canonical_ids

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
MIN_VOTES = 100
MIN_N = 40


def period(year: int) -> str:
    if 1995 <= year <= 1999:
        return "1995–99"
    if 1990 <= year <= 1994:
        return "1990–94"
    return f"{min(year // 10 * 10, 2020)}s"


def main() -> None:
    corpus = {str(pid) for pid in canonical_ids()}
    years = {}
    has_face = {}
    with (DATA / "faces_v2.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["year"]:
                years[r["id"]] = int(float(r["year"]))
            has_face[r["id"]] = float(r["n_faces"] or 0) > 0
    votes = {}
    with (DATA / "horror_movies.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            votes[r["id"]] = float(r.get("vote_count") or 0)
    star = {}
    with (DATA / "qa" / "celebrity_cast_verification.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            star[r["id"]] = bool(json.loads(r["cast_match"] or "[]"))

    print(
        f"{sum(has_face.get(i, False) for i in corpus):,} corpus posters with a face, "
        f"{sum(star.get(i, False) for i in corpus):,} with a cast-verified star"
    )
    for label, keep in (
        ("all corpus posters", lambda i: True),
        (f"films with {MIN_VOTES}+ TMDB votes", lambda i: votes.get(i, 0) >= MIN_VOTES),
    ):
        groups: dict[str, list[bool]] = {}
        for i in corpus:
            if i in years and keep(i):
                groups.setdefault(period(years[i]), []).append(star.get(i, False))
        print(label)
        for p in sorted(groups):
            v = groups[p]
            if len(v) >= MIN_N:
                print(f"  {p:8s} n={len(v):6,}  {sum(v) / len(v):6.1%}")


if __name__ == "__main__":
    main()
