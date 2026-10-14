#!/usr/bin/env python3
"""Does what the poster shows predict how audiences and critics rate the film?

Audience = IMDb rating x 10 (films with MIN_VOTES+ IMDb votes); critics =
Metascore (0-100), both from OMDb (fetch_omdb_ratings.py). The Rotten Tomatoes
Tomatometer is a share of positive reviews, not an average, so it is only
mixed in with --with-rt as a robustness check.

For each poster trait, the effect is the mean score with the trait minus
without it, within the same decade (decades weighted by the smaller group),
with a bootstrap 95% interval. Traits: CLIP census creature, OWLv2 weapon box
(Nova false positives dropped, score >= 0.3, as the site), YuNet face,
cast-verified Rekognition star, ornate vs minimal title register, darkest
brightness quartile.

Result (2026-10-13, 1,714 films with a Metascore): every effect is within
2.5 points. Ornate vs minimal title: critics -0.7 (-3.9, +2.3). Weapon and
dark posters widen the audience-critics gap by under 2 points, with intervals
that barely clear zero. Source of the "critics didn't get the memo" line in
the typography section.

  python3 poster_promise_reviews.py [--with-rt]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from pathlib import Path

from build_site import drop_nova_false_positives
from corpus import canonical_ids

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OMDB = DATA / "qa" / "omdb" / "omdb.jsonl"
MIN_VOTES = 100
MIN_CELL = 5
BOOT = 500


def present(v) -> bool:
    return v not in (None, "", "N/A")


def load_scores(with_rt: bool) -> dict[str, dict[str, float]]:
    corpus = {str(pid) for pid in canonical_ids()}
    films = {}
    for line in OMDB.open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("Response") != "True" or str(r["id"]) not in corpus:
            continue
        votes = int(r["imdbVotes"].replace(",", "")) if present(r.get("imdbVotes")) else 0
        if not present(r.get("imdbRating")) or votes < MIN_VOTES:
            continue
        critics = float(r["Metascore"]) if present(r.get("Metascore")) else None
        if critics is None and with_rt:
            for x in r.get("Ratings", []):
                if x["Source"] == "Rotten Tomatoes":
                    critics = float(x["Value"].rstrip("%"))
        if critics is not None:
            aud = float(r["imdbRating"]) * 10
            films[str(r["id"])] = {"audience": aud, "critics": critics, "gap": aud - critics}
    return films


def traits(films) -> dict:
    def rows(name):
        with (DATA / name).open(newline="", encoding="utf-8") as f:
            yield from csv.DictReader(f)

    face = {r["id"]: float(r["n_faces"] or 0) > 0 for r in rows("faces_v2.csv")}
    creature = {r["id"]: r["is_creature"] == "True" for r in rows("census.csv")}
    register = {r["id"]: r["register"] for r in rows("typography.csv")}
    bright = {r["id"]: float(r["brightness"]) for r in rows("posters.csv") if r["brightness"]}
    star = {
        r["id"]: bool(json.loads(r["cast_match"] or "[]"))
        for r in rows("qa/celebrity_cast_verification.csv")
    }
    boxes = drop_nova_false_positives(
        json.loads((DATA / "weapon_boxes.json").read_text(encoding="utf-8"))
    )
    weapon = {k: any((b.get("score") or 0) >= 0.3 for b in v) for k, v in boxes.items() if v}
    dark_cut = statistics.quantiles([bright[i] for i in films if i in bright], n=4)[0]
    return {
        "creature": lambda i: creature.get(i, False),
        "weapon": lambda i: weapon.get(i, False),
        "face": lambda i: face.get(i, False),
        "cast star": lambda i: star.get(i, False),
        "ornate title (vs minimal)": lambda i: {"ornate": True, "minimal": False}.get(
            register.get(i)
        ),
        "dark poster": lambda i: bright.get(i, float("inf")) <= dark_cut,
    }


def effect(ids, has, films, decade, key) -> float:
    groups: dict[int, tuple[list[float], list[float]]] = {}
    for i in ids:
        v = has(i)
        if v is None:
            continue
        groups.setdefault(decade[i], ([], []))[0 if v else 1].append(films[i][key])
    num = den = 0.0
    for with_, without in groups.values():
        if len(with_) >= MIN_CELL and len(without) >= MIN_CELL:
            w = min(len(with_), len(without))
            num += w * (statistics.mean(with_) - statistics.mean(without))
            den += w
    return num / den if den else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-rt", action="store_true", help="use the Tomatometer when no Metascore")
    args = ap.parse_args()
    films = load_scores(args.with_rt)
    decade = {}
    with (DATA / "faces_v2.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["id"] in films and r["year"]:
                decade[r["id"]] = min(max(int(float(r["year"])), 1960) // 10 * 10, 2020)
    ids = sorted(i for i in films if i in decade)
    gap = statistics.mean(films[i]["gap"] for i in ids)
    print(f"{len(ids):,} films, audience minus critics on average {gap:+.1f}")
    print("trait: with minus without, same decade (95% CI)")
    rnd = random.Random(3)
    lo, hi = int(0.025 * BOOT), int(0.975 * BOOT) - 1
    for name, has in traits(films).items():
        cells = []
        for key in ("audience", "critics", "gap"):
            est = effect(ids, has, films, decade, key)
            boot = sorted(
                effect(rnd.choices(ids, k=len(ids)), has, films, decade, key) for _ in range(BOOT)
            )
            cells.append(f"{key} {est:+5.1f} ({boot[lo]:+.1f}, {boot[hi]:+.1f})")
        print(f"  {name:26s} " + "   ".join(cells))


if __name__ == "__main__":
    main()
