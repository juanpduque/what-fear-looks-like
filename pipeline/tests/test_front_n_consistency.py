"""The published corpus n must match across README, index.html, i18n and
series.js. Reuses the real checker from sync_front_n so the test can't drift
from the tool.
"""
from __future__ import annotations

from sync_front_n import check_front_n


def test_front_copy_n_in_sync():
    issues = check_front_n()
    assert not issues, "front-end corpus n mismatches:\n  - " + "\n  - ".join(issues)
