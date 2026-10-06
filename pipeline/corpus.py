"""Canonical published corpus — single source of truth for every site builder.

The id list is produced by build_corpus.py (criteria in docs/CORPUS.md) and
read here. Builders filter per-poster CSVs by it at build time; raw CSVs are
never mutated.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
CANONICAL_IDS = DATA / "canonical_ids.txt"


@lru_cache(maxsize=1)
def canonical_ids() -> frozenset[int]:
    if not CANONICAL_IDS.is_file():
        raise SystemExit(f"falta {CANONICAL_IDS} — corre pipeline/build_corpus.py")
    ids = frozenset(
        int(x) for x in CANONICAL_IDS.read_text().split() if x.strip().isdigit()
    )
    if not ids:
        raise SystemExit(f"{CANONICAL_IDS} vacio")
    return ids


def corpus_n() -> int:
    return len(canonical_ids())
