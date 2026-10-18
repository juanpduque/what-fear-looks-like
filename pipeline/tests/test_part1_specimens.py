"""The Part I specimen strip: every hand-typed caption must match the data.

The Color River strip in site/src/charts/essay.js (CR_RED ... CR_BLACK) lists one
real poster per era with a caption like "1980 · 82%": the share of that sheet in
the row's hue band. Those numbers are typed by hand, and TMDB changing a film's
primary poster silently made nine of them wrong (a 97% black sheet that now
measures 28%). This compares them to site/data/lookup.js, the file the autopsy
reads, so a stale caption fails CI instead of reaching the page.
"""

from __future__ import annotations

import re

import pytest
from conftest import ROOT, SITE_DATA, js_payload

ESSAY_JS = ROOT / "site" / "src" / "charts" / "essay.js"

# CR_* constant -> index into LOOKUP[id]["bands"] (build_lookup.BANDS order:
# red, warm, green, blue, purple, dark/grey).
ROWS = {
    "CR_RED": 0,
    "CR_WARM": 1,
    "CR_GREEN": 2,
    "CR_BLUE": 3,
    "CR_PURPLE": 4,
    "CR_BLACK": 5,
}

# lookup.js rounds bands to 2 decimals and the caption to whole percent.
TOLERANCE_POINTS = 2
# A specimen is "the sheet where that band actually dominates", so a caption
# under this is a weak example even if its number is true.
MIN_SHARE = 20

ENTRY = re.compile(r"""\[(\d+), (?:'([^']*)'|"([^"]*)"), '(\d{4})', '(\d+)%'\]""")


def specimen_rows(js: str) -> dict[str, list[tuple[int, str, int, int]]]:
    """{CR_RED: [(id, title, year, caption_pct), ...], ...} parsed from essay.js."""
    out = {}
    for name in ROWS:
        block = re.search(rf"const {name} = \[(.*?)\n\s*\];", js, re.S)
        assert block, f"{name} not found in essay.js"
        out[name] = [
            (int(i), t1 or t2, int(y), int(p)) for i, t1, t2, y, p in ENTRY.findall(block.group(1))
        ]
    return out


@pytest.fixture(scope="session")
def rows():
    return specimen_rows(ESSAY_JS.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def explorer_by_id():
    data, _ = js_payload(SITE_DATA / "explorer.js", "const POSTERS=")
    return {r[7]: r for r in data}


@pytest.fixture(scope="session")
def lookup():
    data, _ = js_payload(SITE_DATA / "lookup.js", "window.LOOKUP=")
    return data


def test_every_row_has_six_specimens(rows):
    for name, entries in rows.items():
        assert len(entries) == 6, f"{name}: {len(entries)} specimens, expected one per era (6)"


def test_specimens_are_in_the_corpus(rows, explorer_by_id):
    """An id outside the explorer has no TMDB path, so its image would 404."""
    for name, entries in rows.items():
        for pid, title, *_ in entries:
            assert pid in explorer_by_id, f"{name}: {title} ({pid}) is not in the published corpus"


def test_year_and_title_match_the_corpus(rows, explorer_by_id):
    for name, entries in rows.items():
        for pid, title, year, _ in entries:
            row = explorer_by_id[pid]
            assert (year, title) == (row[0], row[3]), (
                f"{name}: caption says {title} ({year}), corpus has {row[3]} ({row[0]})"
            )


def test_captions_follow_the_data(rows, lookup):
    stale = []
    for name, entries in rows.items():
        band = ROWS[name]
        for pid, title, year, pct in entries:
            actual = round(lookup[str(pid)]["bands"][band] * 100)
            if abs(actual - pct) > TOLERANCE_POINTS:
                stale.append(f"{name}: {title} ({year}) says {pct}%, data says {actual}%")
    assert not stale, "stale captions:\n  " + "\n  ".join(stale)


def test_specimens_actually_have_the_band(rows, lookup):
    weak = []
    for name, entries in rows.items():
        band = ROWS[name]
        for pid, title, year, _ in entries:
            actual = round(lookup[str(pid)]["bands"][band] * 100)
            if actual < MIN_SHARE:
                weak.append(f"{name}: {title} ({year}) is only {actual}% in its band")
    assert not weak, f"weak specimens (< {MIN_SHARE}%):\n  " + "\n  ".join(weak)


# Part VII strips: "N% red · M% blood" typed by hand against lookup.js (red share, CLIP blood score).
BLOOD_ENTRY = re.compile(
    r"""\[(\d+), (?:'([^']*)'|"([^"]*)"), '(\d{4})', '(\d+)% red · (\d+)% blood'\]"""
)


def blood_rows(js: str):
    out = {}
    for name in ("TB_PIXEL", "TB_SEMANTIC"):
        block = re.search(rf"const {name} = \[(.*?)\n\s*\];", js, re.S)
        assert block, f"{name} not found in essay.js"
        out[name] = [
            (int(i), t1 or t2, int(y), int(r), int(b))
            for i, t1, t2, y, r, b in BLOOD_ENTRY.findall(block.group(1))
        ]
    return out


def test_blood_captions_follow_the_data(explorer_by_id, lookup):
    rows = blood_rows(ESSAY_JS.read_text(encoding="utf-8"))
    assert all(len(v) == 6 for v in rows.values())
    stale = []
    for name, entries in rows.items():
        for pid, title, year, red, blood in entries:
            assert pid in explorer_by_id, f"{name}: {title} ({pid}) is not in the published corpus"
            row = explorer_by_id[pid]
            if (year, title) != (row[0], row[3]):
                stale.append(f"{name}: {title} ({year}) is {row[3]} ({row[0]}) in the corpus")
            rec = lookup[str(pid)]
            actual_red = round(rec["red"] * 100)
            actual_blood = round(rec["sem"].get("blood", 0) * 100)
            if abs(actual_red - red) > TOLERANCE_POINTS or actual_blood != blood:
                stale.append(
                    f"{name}: {title} says {red}% red / {blood}% blood, "
                    f"data says {actual_red}% / {actual_blood}%"
                )
    assert not stale, "stale captions:\n  " + "\n  ".join(stale)
