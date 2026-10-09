#!/usr/bin/env python3
"""Does the published title box cover the title ink? Corpus-wide, no new API.

Autopsy draws attributes.csv text_*. Manual review sees many that miss the
lettering. This scores every canonical id that already has Rek DetectText LINEs:

  1. Keep lines whose text fuzzy-matches the catalog title (or, for
     letter-spaced titles, the row of single letters that spells it).
  2. Measure what fraction of that title-line area sits inside the published box.
  3. Rank misses (cover low) for visual QA.

  python3 qa_title_box_fit.py
  python3 qa_title_box_fit.py --min-cover 0.4

Outputs:
  data/qa/title_box_fit.csv
  data/qa/title_box_fit_miss.csv
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from corpus import canonical_ids
from title_boxes_rekognition import title_line_hits

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "qa" / "title_box_fit.csv"
OUT_MISS = DATA / "qa" / "title_box_fit_miss.csv"

LINE_CSVS = [
    DATA / "qa" / "rekognition_text_boxes_site_full" / "rekognition_text_boxes_site_full.csv",
    DATA / "rekognition_text_boxes.csv",
    DATA / "backfills_ec2_20261005" / "rekognition_text_boxes_tmdb.csv",
    DATA / "qa" / "type_mix" / "rekognition_text_boxes_site_full_seed.csv",
    DATA / "qa" / "omdb_gap" / "rekognition_text_boxes_omdb_gap.csv",
]

MATCH_MIN = 0.72


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def inter_area(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    iw = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    ih = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return iw * ih


def union_box(boxes: list[tuple[float, float, float, float]]):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


def load_titles(keep: set[int]) -> dict[int, str]:
    out = {}
    with (DATA / "posters.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                i = int(r["id"])
            except (KeyError, ValueError):
                continue
            if i in keep:
                out[i] = (r.get("title") or "").strip()
    return out


def load_pub_boxes(keep: set[int]) -> dict[int, tuple[float, float, float, float]]:
    out = {}
    with (DATA / "attributes.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                i = int(r["id"])
                box = (
                    float(r["text_x"]),
                    float(r["text_top"]),
                    float(r["text_w"]),
                    float(r["text_h"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if i not in keep:
                continue
            if box[2] <= 0 or box[3] <= 0 or box[0] < 0 or box[1] < 0:
                continue
            out[i] = box
    return out


def load_lines(keep: set[int]) -> dict[int, list[dict]]:
    best: dict[int, list[dict]] = {}
    for path in LINE_CSVS:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    i = int(r["id"])
                except (KeyError, ValueError):
                    continue
                if i not in keep:
                    continue
                raw = r.get("lines") or ""
                lines = []
                if raw and raw not in ("nan", "[]"):
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = []
                    if isinstance(parsed, list):
                        lines = [
                            x
                            for x in parsed
                            if isinstance(x, dict) and x.get("box") and x.get("text")
                        ]
                prev = best.get(i)
                if prev is None or len(lines) > len(prev):
                    best[i] = lines
    return best


def score_one(title: str, pub, lines: list[dict], min_match: float):
    hits = title_line_hits(lines, title, min_match)
    if not hits:
        return None
    hits.sort(reverse=True)
    title_boxes = [b for _, b, _ in hits]
    areas = [max(1e-9, b[2] * b[3]) for b in title_boxes]
    covered = sum(inter_area(b, pub) for b in title_boxes)
    cover = covered / sum(areas)
    ink = union_box(title_boxes)
    return {
        "n_title_lines": len(hits),
        "best_match": round(hits[0][0], 3),
        "cover": round(cover, 3),
        "iou": round(iou(pub, ink), 3),
        "ink": ink,
        "ocr": " | ".join(t for _, _, t in hits[:4]),
    }


def verdict(cover: float, min_cover: float) -> str:
    if cover < min_cover:
        return "miss"
    if cover < 0.6:
        return "weak"
    return "ok"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-cover", type=float, default=0.4)
    ap.add_argument("--min-match", type=float, default=MATCH_MIN)
    args = ap.parse_args()

    keep = set(canonical_ids())
    titles = load_titles(keep)
    pubs = load_pub_boxes(keep)
    lines = load_lines(keep)

    rows = []
    counts = {"ok": 0, "weak": 0, "miss": 0, "no_title_line": 0, "no_lines": 0, "no_box": 0}
    for i in sorted(keep):
        title = titles.get(i, "")
        pub = pubs.get(i)
        lns = lines.get(i)
        rec = {
            "id": i,
            "title": title,
            "verdict": "",
            "cover": "",
            "iou": "",
            "best_match": "",
            "n_title_lines": "",
            "n_lines": len(lns) if lns is not None else "",
            "pub": "",
            "ink": "",
            "ocr": "",
            "review_url": f"http://127.0.0.1:5176/what-fear-looks-like/?id={i}&lang=es#lookup",
        }
        if pub:
            rec["pub"] = ",".join(f"{x:.4f}" for x in pub)
        if lns is None:
            rec["verdict"] = "no_lines"
        elif pub is None:
            rec["verdict"] = "no_box"
        else:
            hit = score_one(title, pub, lns, args.min_match)
            if hit is None:
                rec["verdict"] = "no_title_line"
                rec["n_lines"] = len(lns)
            else:
                rec.update(
                    {
                        "verdict": verdict(hit["cover"], args.min_cover),
                        "cover": hit["cover"],
                        "iou": hit["iou"],
                        "best_match": hit["best_match"],
                        "n_title_lines": hit["n_title_lines"],
                        "ink": ",".join(f"{x:.4f}" for x in hit["ink"]),
                        "ocr": hit["ocr"],
                    }
                )
        counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1
        rows.append(rec)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    misses = [r for r in rows if r["verdict"] == "miss"]
    misses.sort(key=lambda r: (float(r["cover"] or 0), float(r["iou"] or 0)))
    with OUT_MISS.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(misses)

    n = len(keep)
    scored = counts["ok"] + counts["weak"] + counts["miss"]
    print(f"canonical {n:,}")
    print(f"scored (title lines ∩ published box) {scored:,}")
    for k in ("ok", "weak", "miss", "no_title_line", "no_lines", "no_box"):
        print(f"  {k:16} {counts[k]:,}")
    if scored:
        print(f"miss rate among scored {counts['miss'] / scored:.1%}")
    print(f"wrote {OUT}")
    print(f"wrote {OUT_MISS} ({len(misses):,} misses)")
    print("worst misses:")
    for r in misses[:12]:
        print(f"  {r['id']:>8} cover={r['cover']} iou={r['iou']}  {r['title']}")


if __name__ == "__main__":
    main()
