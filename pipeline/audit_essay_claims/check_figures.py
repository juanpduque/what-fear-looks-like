"""Recompute the essay figures that were typed by hand: cast-star shares, census vs a second reader,
ornate-share decade trend. Reads the committed CSVs under pipeline/data and the site's lookup.js.
(Title size by language: world_title_size.py. Reviews: poster_promise_reviews.py.)

    python3 audit_essay_claims/check_figures.py
"""

import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "pipeline" / "data"
IDS = {int(x) for x in (DATA / "canonical_ids.txt").read_text().split()}


def wilson(k: int, n: int) -> tuple[float, float, float]:
    p, z = k / n, 1.96
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p * 100, (c - w) * 100, (c + w) * 100


def stars() -> None:
    v = pd.read_csv(DATA / "qa" / "celebrity_cast_verification.csv")
    v = v[v.id.isin(IDS)].drop_duplicates("id")
    v["star"] = v.cast_match.fillna("[]").map(lambda s: len(json.loads(s)) > 0)
    print("posters with a cast-verified star:", int(v.star.sum()))
    posters = pd.read_csv(DATA / "posters.csv")
    posters = posters[posters.id.isin(IDS)][["id", "year"]]
    votes = pd.read_csv(DATA / "horror_movies.csv", usecols=["id", "vote_count"])
    d = posters.merge(votes, on="id").merge(v[["id", "star"]], on="id", how="left")
    d["star"] = d.star.fillna(False).astype(bool)
    for lo, hi in ((1995, 1999), (2015, 2026)):
        for name, sel in (
            ("well-known (100+ votes)", d.vote_count >= 100),
            ("rest", d.vote_count < 100),
        ):
            s = d[d.year.between(lo, hi) & sel]
            p, a, b = wilson(int(s.star.sum()), len(s))
            print(f"  {lo}-{hi} {name}: {p:.0f}% [{a:.0f}, {b:.0f}] n={len(s)}")


def census_vs_nova() -> None:
    text = (ROOT / "site" / "data" / "lookup.js").read_text(encoding="utf-8")
    lookup = json.JSONDecoder().raw_decode(text[text.index("window.LOOKUP=") + 14 :])[0]
    c = pd.read_csv(DATA / "census.csv")
    c = c[c.id.isin(IDS)].drop_duplicates("id")
    c["nova"] = c.id.map(lambda i: lookup.get(str(i), {}).get("nova_creature"))
    lab = c[~c.label.isin(["uncertain", "none"]) & c.nova.notna()]
    named = lab[lab.nova != "none"]
    print(
        f"census label == Nova: {(lab.label == lab.nova).mean() * 100:.1f}% of {len(lab)} labeled;"
    )
    print(
        f"  {(named.label == named.nova).mean() * 100:.1f}% of {len(named)} where Nova names a creature"
    )
    c["dec"] = c.year // 10 * 10
    for dec in (2010, 2020):
        top = c[(c.dec == dec) & (c.nova != "none")].nova.value_counts().head(3).to_dict()
        print(f"  Nova top creatures {dec}s:", top)


def typography_trend() -> None:
    t = pd.read_csv(DATA / "typography.csv")
    t = t[t.id.isin(IDS)]
    t["dec"] = t.year // 10 * 10
    g = t[t.dec >= 1920].assign(orn=lambda x: x.register == "ornate").groupby("dec").orn.mean()
    print(
        "ornate share vs decade, r =", round(g.index.to_series().corr(g), 3), f"({len(g)} decades)"
    )
    print(
        "per poster, axis vs year, r =",
        round(t[t.year >= 1920].year.corr(t[t.year >= 1920]["axis"]), 3),
    )


if __name__ == "__main__":
    stars()
    census_vs_nova()
    typography_trend()
