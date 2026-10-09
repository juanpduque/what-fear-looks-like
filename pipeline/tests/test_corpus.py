"""Unit tests for corpus.py — the single source of truth for the published n."""
from __future__ import annotations

from pathlib import Path

import corpus


def test_canonical_ids_nonempty(canonical):
    assert len(canonical) > 0


def test_canonical_ids_are_ints(canonical):
    assert all(isinstance(i, int) for i in canonical)
    assert all(i > 0 for i in canonical)


def test_corpus_n_matches_len(canonical):
    assert corpus.corpus_n() == len(canonical)


def test_canonical_ids_cached():
    # lru_cache: repeated calls return the same frozenset object.
    assert corpus.canonical_ids() is corpus.canonical_ids()


def test_canonical_ids_no_duplicates_in_file():
    raw = [
        x
        for x in Path(corpus.CANONICAL_IDS).read_text().split()
        if x.strip().isdigit()
    ]
    assert len(raw) == len(set(raw)), "canonical_ids.txt has duplicate ids"


def test_corpus_n_in_expected_band(corpus_n):
    # Published corpus, not the ~72k raw TMDB set or tiny exclusion lists.
    assert 20_000 <= corpus_n <= 60_000
