"""Summarise sens.jsonl: the same measures on TMDB's poster vs the IMPAwards release-year poster.

  python3 sens_summary.py sens.jsonl

Per decade: mean brightness, share of posters with a face, mean text area, both for the TMDB
image the essay measures and for the release-year original, over the same films. Also the
noise floor: pairs whose images are the same artwork (pHash distance <= 10) differ only by
JPEG/scan/crop, so their spread is the smallest difference the comparison can resolve.
"""

import json
import sys
from collections import defaultdict
from statistics import mean

SAME_ART = 10


def load(path):
    with open(path, encoding="utf-8") as f:
        return [r for r in map(json.loads, f) if "tmdb" in r and "impa" in r]


def by_decade(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[r["year"] // 10 * 10].append(r)
    return dict(sorted(groups.items()))


def stat(rows, side, key):
    return mean(r[side][key] for r in rows)


def face_share(rows, side):
    return 100 * mean(r[side]["n_faces"] > 0 for r in rows)


def main(path):
    rows = load(path)
    print(f"{len(rows)} films measured on both images\n")
    print(
        "decade    n | brightness TMDB / original | faces % TMDB / original | text area TMDB / original"
    )
    for dec, g in by_decade(rows).items():
        print(
            f"{dec}s {len(g):>4} | {stat(g, 'tmdb', 'brightness'):>8.1f} / {stat(g, 'impa', 'brightness'):<8.1f}"
            f"      | {face_share(g, 'tmdb'):>5.0f} / {face_share(g, 'impa'):<5.0f}"
            f"       | {stat(g, 'tmdb', 'text_area'):.3f} / {stat(g, 'impa', 'text_area'):.3f}"
        )
    same = [r for r in rows if r["dist"] <= SAME_ART]
    print(f"\nNoise floor: {len(same)} pairs with the same artwork (pHash distance <= {SAME_ART})")
    for label, key, scale in (
        ("brightness", "brightness", 1),
        ("near-black share, pp", "dark_share", 100),
        ("diagonal score", "diagonal_score", 1),
    ):
        d = mean((r["tmdb"][key] - r["impa"][key]) * scale for r in same)
        print(f"  mean TMDB - original, {label}: {d:+.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
