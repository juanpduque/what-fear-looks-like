"""Is the TMDB-vs-original offset of the diagonal score constant across decades?

  python3 diag_offset.py results/sens.jsonl results/impa_full.jsonl

The diagonal score is the least stable measure between image sources (it counts Hough line
segments, which depend on resolution and compression). This reports, in chart points
(score x 100): the TMDB minus release-year offset by decade (same-artwork pairs and all pairs),
whether it tracks the pixel-count ratio, and the fall from 1940-59 to 1980-99 inside each source.
"""

import json
import math
import statistics as st
import sys
from collections import defaultdict

SAME_ART = 10


def load(path):
    with open(path, encoding="utf-8") as f:
        return [r for r in map(json.loads, f) if "tmdb" in r]


def offset(r):
    return (r["tmdb"]["diagonal_score"] - r["impa"]["diagonal_score"]) * 100


def mean_ci(values):
    m = st.fmean(values)
    return m, 1.96 * st.stdev(values) / math.sqrt(len(values))


def by_decade(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[r["year"] // 10 * 10].append(r)
    return dict(sorted(groups.items()))


def offsets(rows, title):
    print(f"\n{title}")
    for dec, g in by_decade(rows).items():
        if len(g) < 3:
            print(f"  {dec}s n={len(g)} (too few)")
            continue
        m, h = mean_ci([offset(r) for r in g])
        print(f"  {dec}s n={len(g):>3}  {m:+5.1f} pts  [{m - h:+.1f}, {m + h:+.1f}]")
    m, h = mean_ci([offset(r) for r in rows])
    print(f"  total n={len(rows):>3}  {m:+5.1f} pts  [{m - h:+.1f}, {m + h:+.1f}]")


def fall(rows, side, early=(1940, 1959), late=(1980, 1999)):
    pick = lambda lo, hi: [r[side]["diagonal_score"] * 100 for r in rows if lo <= r["year"] <= hi]  # noqa: E731
    a, b = pick(*early), pick(*late)
    diff = st.fmean(b) - st.fmean(a)
    se = math.sqrt(st.variance(a) / len(a) + st.variance(b) / len(b))
    print(
        f"  {side}: {st.fmean(a):.1f} -> {st.fmean(b):.1f}  diff {diff:+.1f} "
        f"[{diff - 1.96 * se:+.1f}, {diff + 1.96 * se:+.1f}]  (n {len(a)} -> {len(b)})"
    )


def corr(x, y):
    mx, my = st.fmean(x), st.fmean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    return num / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))


def main(sens_path, impa_path):
    rows = load(sens_path)
    sizes = {}
    with open(impa_path, encoding="utf-8") as f:
        for r in map(json.loads, f):
            if "tmdb_size" in r:
                sizes[r["id"]] = r
    same = [r for r in rows if r["dist"] <= SAME_ART]
    offsets(same, f"Same artwork (pHash <= {SAME_ART}): TMDB - original")
    offsets(rows, "All pairs: TMDB - original")
    ratio = [
        math.log(sizes[r["id"]]["tmdb_size"][0] * sizes[r["id"]]["tmdb_size"][1])
        - math.log(sizes[r["id"]]["impa_size"][0] * sizes[r["id"]]["impa_size"][1])
        for r in same
    ]
    print(
        f"\ncorr(offset, log pixel ratio TMDB/original), same artwork: {corr([offset(r) for r in same], ratio):.2f}"
    )
    print("\nFall 1940-59 -> 1980-99 inside each source (chart points):")
    fall(rows, "impa")
    fall(rows, "tmdb")


if __name__ == "__main__":
    main(*sys.argv[1:3])
