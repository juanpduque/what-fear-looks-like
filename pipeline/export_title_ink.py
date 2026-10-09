#!/usr/bin/env python3
"""Sidecar of Rek title-line unions for autopsy when attributes text_* miss.

Does not rewrite attributes.csv or essay TEXT_PTS. Autopsy paints these
boxes when title_box_fit says miss/weak; specimen TITLE_BOX_OVERRIDE still wins.

  python3 qa_title_box_fit.py   # refresh first if DetectText lines changed
  python3 export_title_ink.py

Writes site/data/title_ink.json  {id: [tx, tt, tw, th]}
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIT = HERE / "data" / "qa" / "title_box_fit.csv"
OUT = HERE.parent / "site" / "data" / "title_ink.json"
RESCUE = frozenset({"miss", "weak"})


def main() -> None:
    if not FIT.is_file():
        raise SystemExit(f"falta {FIT} — corre pipeline/qa_title_box_fit.py")
    ink: dict[str, list[float]] = {}
    with FIT.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("verdict") not in RESCUE:
                continue
            raw = (r.get("ink") or "").strip()
            if not raw:
                continue
            try:
                box = [round(float(x), 4) for x in raw.split(",")]
            except ValueError:
                continue
            if len(box) != 4 or box[2] <= 0 or box[3] <= 0:
                continue
            ink[str(int(r["id"]))] = box
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(ink, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} n={len(ink):,}")


if __name__ == "__main__":
    main()
