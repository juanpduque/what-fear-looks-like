"""Shared pytest fixtures and path helpers.

These tests are intentionally dependency-light: standard library only, no
pandas/torch/transformers. They validate the *committed* artifacts
(canonical_ids.txt + site/data/*.js) that the published site actually serves,
so they run in CI in milliseconds and never need the heavy, gitignored
metric CSVs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parent.parent
ROOT = PIPELINE_DIR.parent
DATA = PIPELINE_DIR / "data"
SITE_DATA = ROOT / "site" / "data"

# Make `import corpus`, `import sync_front_n`, etc. resolve.
sys.path.insert(0, str(PIPELINE_DIR))


def js_payload(path: Path, marker: str):
    """Parse the JSON blob that follows `marker` in a generated site/data/*.js.

    Mirrors _js_payload() in check_site_invariants.py: the file is
    `<marker><json>;` possibly spread over lines. Returns (data, first_line).
    """
    text = path.read_text(encoding="utf-8")
    start = text.index(marker) + len(marker)
    return json.loads(text[start:].rstrip().rstrip(";")), text.split("\n", 1)[0]


@pytest.fixture(scope="session")
def canonical() -> frozenset[int]:
    from corpus import canonical_ids

    return canonical_ids()


@pytest.fixture(scope="session")
def corpus_n(canonical) -> int:
    return len(canonical)
