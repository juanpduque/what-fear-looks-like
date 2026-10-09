#!/usr/bin/env python3
"""Sidecar of Rekognition Custom Labels medium for autopsy.

Does not rewrite medium.csv, lookup.js, or essay series. Autopsy reads
site/data/medium_cl.json; CLIP p_painted stays a QA note.

  python3 export_medium_cl.py

Writes {id: [pred, conf]}  pred in painted|photo|composite
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "data" / "qa" / "medium_custom_labels" / "infer_full.csv"
OUT = HERE.parent / "site" / "data" / "medium_cl.json"
ALLOWED = frozenset({"painted", "photo", "composite"})


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"falta {SRC}")
    out: dict[str, list] = {}
    with SRC.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("status") != "ok":
                continue
            pred = (r.get("pred") or "").strip()
            if pred not in ALLOWED:
                continue
            try:
                pid = str(int(r["id"]))
                conf = round(float(r["confidence"]), 3)
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= conf <= 1):
                continue
            out[pid] = [pred, conf]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} n={len(out):,}")


if __name__ == "__main__":
    main()
