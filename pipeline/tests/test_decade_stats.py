"""The per-decade n and 95% intervals shown next to the River, Typography, Census and Blood charts.

site/data/series.js carries DECADE_STATS beside the series it describes (RIVER, TYPO,
BLOOD_SEMANTIC, CENSUS_SERIES). This checks, from the committed files only, that each interval
brackets its plotted value and that each n is the number of posters the explorer holds for that
decade, so a chart can't show a number its readout contradicts.
"""

from __future__ import annotations

import json
import re
from collections import Counter

import pytest
from conftest import SITE_DATA, js_payload

ROUND = 0.15  # series and intervals are both rounded to 1 decimal (TYPO to 4, as a fraction)


SERIES = (SITE_DATA / "series.js").read_text(encoding="utf-8")


def load(marker: str):
    """The JSON value that follows `marker` in series.js (a file of several const statements)."""
    start = SERIES.index(marker) + len(marker)
    text = re.sub(r"\s*//[^\n]*|/\*.*?\*/", "", SERIES[start:], flags=re.S)
    return json.JSONDecoder().raw_decode(text.lstrip())[0]


@pytest.fixture(scope="module")
def stats():
    return load("const DECADE_STATS=")


@pytest.fixture(scope="module")
def decades():
    return [int(d[:4]) for d in load("const DECADES=")]


def inside(value, ci, tol=ROUND):
    return ci[0] - tol <= value <= ci[1] + tol


def test_n_matches_the_explorer(stats, decades):
    explorer, _ = js_payload(SITE_DATA / "explorer.js", "const POSTERS=")
    per_decade = Counter(row[0] // 10 * 10 for row in explorer)
    expected = [per_decade[d] for d in decades]
    for chart in ("river", "typo", "blood"):
        assert stats[chart]["n"] == expected, f"{chart}: n differs from the explorer"
    census = stats["census"]
    assert census["n"] == [per_decade[d] for d in census["decades"]]


def test_river_intervals_bracket_the_means(stats):
    river = load("const RIVER=")
    assert len(river) == len(stats["river"]["ci"])
    for di, (row, cis) in enumerate(zip(river, stats["river"]["ci"], strict=True)):
        for band, (value, ci) in enumerate(zip(row, cis, strict=True)):
            assert inside(value, ci), f"decade {di} band {band}: {value} not in {ci}"


def test_typo_intervals_bracket_the_shares(stats):
    typo = load("const TYPO=")
    for di, (row, cis) in enumerate(zip(typo, stats["typo"]["ci"], strict=True)):
        for reg, (value, ci) in enumerate(zip(row, cis, strict=True)):
            assert inside(100 * value, ci, 0.1), f"decade {di} register {reg}: {value} not in {ci}"


def test_blood_intervals_bracket_the_means(stats):
    blood = load("const BLOOD_SEMANTIC=")
    for di, (value, ci) in enumerate(zip(blood, stats["blood"]["ci"], strict=True)):
        assert inside(value, ci), f"decade {di}: {value} not in {ci}"


def test_census_intervals_bracket_the_shares(stats):
    series = load("const CENSUS_SERIES=")
    census = stats["census"]
    for label, pts in series.items():
        assert label in census["ci"], f"no intervals for {label}"
        by_decade = dict(zip(census["decades"], census["ci"][label], strict=True))
        for decade, value in pts:
            assert inside(value, by_decade[decade]), (
                f"{label} {decade}: {value} not in {by_decade[decade]}"
            )


def test_thin_decades_have_wider_intervals(stats):
    """The point of showing them: 74 posters in the 1920s must not look as firm as 14,554."""
    ci, n = stats["river"]["ci"], stats["river"]["n"]
    widths = [hi - lo for lo, hi in (row[5] for row in ci)]
    assert n[0] < n[-1] and widths[0] > 3 * widths[-1]


def test_nova_census_intervals_bracket_the_shares(stats):
    """The second reader of the creature census: same labels and decades, its own n and intervals."""
    series = load("const CENSUS_NOVA=")
    clip = load("const CENSUS_SERIES=")
    census = stats["census"]
    nova = census["nova"]
    assert series.keys() == clip.keys()
    assert len(nova["n"]) == len(census["decades"])
    for label, pts in series.items():
        assert [d for d, _ in pts] == census["decades"], f"{label}: decades differ from CLIP's"
        by_decade = dict(zip(census["decades"], nova["ci"][label], strict=True))
        for decade, value in pts:
            assert inside(value, by_decade[decade]), (
                f"{label} {decade}: {value} not in {by_decade[decade]}"
            )


def test_nova_reads_almost_every_poster(stats):
    """Nova answers for the whole corpus, so its n is within a handful of the CLIP census n."""
    census = stats["census"]
    for decade, n_clip, n_nova in zip(
        census["decades"], census["n"], census["nova"]["n"], strict=True
    ):
        assert n_clip - 10 <= n_nova <= n_clip, f"{decade}: CLIP {n_clip} vs Nova {n_nova}"
