#!/usr/bin/env python3
"""Which signals make an OWLv2 creature box trustworthy, measured against Nova Pro.

Uses the corpus creature boxes Nova Pro judged correct or false_positive
(data/qa/qa_creature_weapon_boxes.csv; "uncertain" verdicts are left out) and
reports, for each rule, the share of boxes it keeps, their precision (share
Nova judged correct) and recall (share of all correct boxes kept).

The autopsy draws a creature box only when its label matches the CLIP census
label and its score is >= 0.3 (site/src/autopsy/layers.js
preferredCreatureBoxes); that rule is the source of the "1 in 5 wrong" copy.

  python3 audit_creature_boxes.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
QA = DATA / "qa" / "qa_creature_weapon_boxes.csv"


def iou(a: list[float], b: list[float]) -> float:
    """Intersection over union of two [x, y, w, h] boxes."""
    iw = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0


def main() -> None:
    faces = {}
    with (DATA / "faces_v2.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            faces[r["id"]] = [
                [float(v) for v in b.split(",")] for b in r["face_boxes"].split("|") if b
            ]
    census = {}
    with (DATA / "census.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            census[r["id"]] = r["label"]
    dino = json.loads((DATA / "creature_boxes_dino.json").read_text(encoding="utf-8"))

    rows = []
    with QA.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["kind"] != "creature" or r["verdict"] not in ("correct", "false_positive"):
                continue
            box = json.loads(r["box"])
            rows.append(
                {
                    "ok": r["verdict"] == "correct",
                    "score": float(r["score"]),
                    "face": max((iou(box, fb) for fb in faces.get(r["id"], [])), default=0.0),
                    "dino": max(
                        (
                            iou(box, d["box"])
                            for d in dino.get(r["id"]) or []
                            if d["label"] == r["label"]
                        ),
                        default=0.0,
                    ),
                    "census": census.get(r["id"]) == r["label"],
                }
            )

    n = len(rows)
    correct = sum(r["ok"] for r in rows)
    rules = {
        "all boxes": lambda r: True,
        "score >= 0.3": lambda r: r["score"] >= 0.3,
        "score >= 0.5": lambda r: r["score"] >= 0.5,
        "box on a YuNet face (IoU >= 0.3)": lambda r: r["face"] >= 0.3,
        "DINO same label (IoU >= 0.3)": lambda r: r["dino"] >= 0.3,
        "label matches census": lambda r: r["census"],
        "score >= 0.3 + census (autopsy)": lambda r: r["score"] >= 0.3 and r["census"],
    }
    print(f"{n:,} Nova-judged creature boxes, {correct / n:.1%} correct")
    print(f"  {'rule':34s} {'kept':>7s} {'precision':>10s} {'recall':>7s}")
    for name, keep in rules.items():
        kept = [r for r in rows if keep(r)]
        hits = sum(r["ok"] for r in kept)
        print(f"  {name:34s} {len(kept) / n:7.1%} {hits / len(kept):10.1%} {hits / correct:7.1%}")


if __name__ == "__main__":
    main()
