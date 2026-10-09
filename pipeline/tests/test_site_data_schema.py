"""Schema + integrity tests for the committed site/data/*.js the site serves.

Lightweight versions of the checks in check_site_invariants.py, but asserted
against only the files that live in git (no gitignored CSV/NPZ inputs needed).
"""
from __future__ import annotations

from datetime import date

import pytest

from conftest import SITE_DATA, js_payload

MAX_YEAR = date.today().year


@pytest.fixture(scope="session")
def explorer():
    rows, head = js_payload(SITE_DATA / "explorer.js", "const POSTERS=")
    return rows, head


@pytest.fixture(scope="session")
def lookup():
    data, head = js_payload(SITE_DATA / "lookup.js", "window.LOOKUP=")
    return data, head


# --- explorer.js ---------------------------------------------------------

def test_explorer_matches_canonical(explorer, canonical):
    rows, _ = explorer
    ids = [r[7] for r in rows]
    assert set(ids) == canonical


def test_explorer_no_duplicate_ids(explorer):
    rows, _ = explorer
    ids = [r[7] for r in rows]
    assert len(ids) == len(set(ids))


def test_explorer_header_has_n(explorer, corpus_n):
    _, head = explorer
    assert f"n={corpus_n}" in head


def test_explorer_years_in_range(explorer):
    rows, _ = explorer
    bad = [r for r in rows if not (1900 <= r[0] <= MAX_YEAR)]
    assert not bad, f"{len(bad)} rows with years outside 1900–{MAX_YEAR}"


# --- lookup.js -----------------------------------------------------------

def test_lookup_keys_match_canonical(lookup, canonical):
    data, _ = lookup
    assert {int(k) for k in data} == canonical


def test_lookup_header_has_n(lookup, corpus_n):
    _, head = lookup
    assert f"n={corpus_n}" in head


# --- globals (ids must be a subset of the corpus) ------------------------

@pytest.mark.parametrize(
    "name,marker",
    [
        ("pose.js", "window.POSE="),
        ("creature_boxes.js", "window.CREATURE_BOXES="),
        ("weapon_boxes.js", "window.WEAPON_BOXES="),
    ],
)
def test_global_ids_within_corpus(name, marker, canonical):
    path = SITE_DATA / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    data, _ = js_payload(path, marker)
    extra = {int(k) for k in data} - canonical
    assert not extra, f"{name} has {len(extra)} ids outside the corpus"


# --- no stray backups shipped -------------------------------------------

def test_no_backup_files_in_site_data():
    stray = sorted(p.name for p in SITE_DATA.iterdir() if ".bak" in p.name)
    assert not stray, f"backup files in site/data: {stray}"
