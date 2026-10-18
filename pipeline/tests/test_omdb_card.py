"""site/data/omdb.json: the autopsy's film card must be well formed and inside the corpus."""

from __future__ import annotations

import json

from conftest import ROOT

CARD = ROOT / "site" / "data" / "omdb.json"
CANON = ROOT / "pipeline" / "data" / "canonical_ids.txt"


def load():
    return json.loads(CARD.read_text(encoding="utf-8"))


def test_every_card_is_a_corpus_film():
    canon = set(CANON.read_text().split())
    stray = [i for i in load() if i not in canon]
    assert not stray, f"{len(stray)} cards outside the corpus, e.g. {stray[:5]}"


def test_cards_have_the_expected_shape():
    for pid, row in load().items():
        assert len(row) == 8, f"{pid}: {row}"
        minutes, short, rated, *strings = row
        assert minutes is None or isinstance(minutes, int)
        assert short in (0, 1)
        assert isinstance(rated, str) and all(isinstance(s, str) for s in strings)


def test_short_flag_follows_the_forty_minute_rule():
    for pid, (minutes, short, *_) in load().items():
        if minutes is not None and minutes < 40:
            assert short == 1, f"{pid}: {minutes} min but not flagged short"
