"""metric_images.py: record() follows the file, check() flags metrics on another file."""

from __future__ import annotations

import csv
import hashlib

import pytest

import metric_images as mi


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    posters = tmp_path / "posters"
    posters.mkdir()
    for pid, data in ((1, b"one"), (2, b"two")):
        (posters / f"{pid}.jpg").write_bytes(data)
    monkeypatch.setattr(mi, "POSTERS", posters)
    monkeypatch.setattr(mi, "OUT", tmp_path / "metric_images.csv")
    monkeypatch.setattr(mi, "STALE", tmp_path / "qa" / "stale.csv")
    sha = {pid: hashlib.sha256(d).hexdigest() for pid, d in ((1, b"one"), (2, b"two"))}
    rows = {pid: {"id": pid, **{m: "" for m in mi.METRICS}} for pid in sha}
    rows[1]["color"] = sha[1]
    rows[2]["color"] = sha[2]
    rows[2]["segmentation"] = "0" * 64  # measured on an older file
    mi.save(rows)
    return sha, posters


def test_check_flags_only_the_metric_on_another_file(ledger):
    assert mi.check(workers=1) == 1
    with mi.STALE.open(newline="", encoding="utf-8") as f:
        stale = list(csv.DictReader(f))
    assert [(r["id"], r["metric"]) for r in stale] == [("2", "segmentation")]


def test_record_follows_a_replaced_file(ledger):
    sha, posters = ledger
    (posters / "1.jpg").write_bytes(b"new art")
    assert mi.check(workers=1) == 1
    mi.record("color", [1], workers=1)
    mi.record("segmentation", [2], workers=1)
    assert mi.check(workers=1) == 0
    assert mi.load()[1]["color"] == hashlib.sha256(b"new art").hexdigest()


def test_record_rejects_unknown_metric(ledger):
    with pytest.raises(KeyError):
        mi.record("colour", [1])


def test_save_keeps_a_symlinked_ledger(ledger, tmp_path, monkeypatch):
    target = tmp_path / "disk" / "metric_images.csv"
    target.parent.mkdir()
    mi.OUT.replace(target)
    link = tmp_path / "link.csv"
    link.symlink_to(target)
    monkeypatch.setattr(mi, "OUT", link)
    mi.record("color", [1], workers=1)
    assert link.is_symlink()
    assert mi.load()[1]["color"]
