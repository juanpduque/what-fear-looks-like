#!/usr/bin/env python3
"""Summarize width/height/bytes of posters_original/ for QA set.

  python3 review_posters_original_sizes.py
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from PIL import Image

DATA = Path(__file__).resolve().parent / "data"
OUT_DIR = DATA / "posters_original"
IDS = DATA / "qa" / "corpus_filter_qa_ids.csv"
REPORT = DATA / "qa" / "posters_original_size_report.csv"
SUMMARY = DATA / "qa" / "posters_original_size_summary.md"


def bucket_w(w: int) -> str:
    if w < 400:
        return "<400"
    if w < 500:
        return "400-499"
    if w < 700:
        return "500-699"
    if w < 1000:
        return "700-999"
    if w < 1500:
        return "1000-1499"
    if w < 2000:
        return "1500-1999"
    return "2000+"


def main() -> None:
    ids = [int(r["id"]) for r in csv.DictReader(IDS.open())]
    rows = []
    missing = 0
    bad = 0
    widths = []
    heights = []
    sizes = []
    wb = Counter()

    for pid in ids:
        p = OUT_DIR / f"{pid}.jpg"
        if not p.exists():
            missing += 1
            continue
        try:
            with Image.open(p) as im:
                w, h = im.size
            b = p.stat().st_size
        except Exception:
            bad += 1
            continue
        rows.append({"id": pid, "width": w, "height": h, "bytes": b})
        widths.append(w)
        heights.append(h)
        sizes.append(b)
        wb[bucket_w(w)] += 1

    fields = ["id", "width", "height", "bytes"]
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        wri = csv.DictWriter(f, fieldnames=fields)
        wri.writeheader()
        for r in rows:
            wri.writerow(r)

    def pct(xs, p):
        if not xs:
            return 0
        ys = sorted(xs)
        i = min(len(ys) - 1, max(0, int(round((p / 100) * (len(ys) - 1)))))
        return ys[i]

    n = len(rows)
    total_gb = sum(sizes) / (1024**3) if sizes else 0
    lines = [
        "# posters_original size review",
        "",
        f"- QA ids: **{len(ids)}**",
        f"- With file: **{n}**",
        f"- Missing: **{missing}**",
        f"- Unreadable: **{bad}**",
        f"- Total disk: **{total_gb:.2f} GB**",
        "",
        "## Width buckets",
        "",
        "| bucket | n |",
        "|---|---:|",
    ]
    for k in ["<400", "400-499", "500-699", "700-999", "1000-1499", "1500-1999", "2000+"]:
        lines.append(f"| {k} | {wb.get(k, 0)} |")
    if widths:
        lines += [
            "",
            "## Percentiles",
            "",
            f"- width p50/p90/p99: **{pct(widths,50)} / {pct(widths,90)} / {pct(widths,99)}**",
            f"- height p50/p90/p99: **{pct(heights,50)} / {pct(heights,90)} / {pct(heights,99)}**",
            f"- bytes p50/p90/p99: **{pct(sizes,50)/1024:.0f} / {pct(sizes,90)/1024:.0f} / {pct(sizes,99)/1024:.0f} KB**",
            "",
            f"Still small for OCR (&lt;700px wide): **{sum(1 for w in widths if w < 700)}** ({100*sum(1 for w in widths if w < 700)/max(n,1):.1f}%)",
            f"Good (&ge;780-ish / ≥700): **{sum(1 for w in widths if w >= 700)}**",
        ]
    SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWrote {REPORT} and {SUMMARY}")


if __name__ == "__main__":
    main()
