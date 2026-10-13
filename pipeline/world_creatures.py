#!/usr/bin/env python3
"""Share of horror posters with a creature, by original language (CLIP census).

A poster has a creature when census.csv is_creature is true (a label from the
18-creature taxonomy at score >= 0.5, as in the essay's monster census). Same
language groups and filters as export_world_faces.py, with Wilson 95%
intervals, for 2000–2026, 2010–2026, and films with 10+ TMDB votes. Raw OWLv2
box counts are not used: see audit_creature_boxes.py.

Source of the creature sentence in the world chart's note (p4_world_note).

  python3 world_creatures.py
"""

from __future__ import annotations

import csv
from pathlib import Path

from corpus import canonical_ids
from export_world_faces import MIN_N, comparable_non_english, wilson

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
MIN_VOTES = 10


def main() -> None:
    langs = {pid: "en" for pid in canonical_ids()}
    langs.update(comparable_non_english())
    years = {}
    with (DATA / "faces_v2.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["year"]:
                years[int(r["id"])] = int(float(r["year"]))
    votes = {}
    with (DATA / "horror_movies.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            votes[int(r["id"])] = float(r.get("vote_count") or 0)
    creature = {}
    with (DATA / "census.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            creature[int(r["id"])] = r["is_creature"] == "True"

    cuts = {
        "2000–2026": lambda pid: 2000 <= years[pid] <= 2026,
        "2010–2026": lambda pid: 2010 <= years[pid] <= 2026,
        f"2000–2026, {MIN_VOTES}+ TMDB votes": lambda pid: (
            2000 <= years[pid] <= 2026 and votes.get(pid, 0) >= MIN_VOTES
        ),
    }
    for name, keep in cuts.items():
        groups: dict[str, list[bool]] = {}
        for pid, lang in langs.items():
            if pid in creature and pid in years and keep(pid):
                groups.setdefault(lang, []).append(creature[pid])
        print(name)
        rows = [(lang, v) for lang, v in groups.items() if len(v) >= MIN_N]
        for lang, v in sorted(rows, key=lambda x: -sum(x[1]) / len(x[1])):
            lo, hi = wilson(sum(v), len(v))
            print(f"  {lang}  n={len(v):6,}  {sum(v) / len(v):6.1%}  ({lo:.1%}–{hi:.1%})")


if __name__ == "__main__":
    main()
