#!/usr/bin/env python3
"""Publish MSI-Net saliency maps for the autopsy as small grayscale WebP.

The PNG maps under data/qa (gitignored, ~1.1 GB) cover far more than the site
shows. This writes only what the autopsy requests:

  site/saliency/{id}.webp                 measured sheet, canonical corpus ids
  site/saliency_alts/{id}_{stem}.webp     alternates in site/data/poster_alts.json
  site/data/saliency.json                 {id: [peak_x, peak_y, top10pct_mass]}

and deletes stale .webp files there, so the folders track the corpus. Files
are tracked with Git LFS (.gitattributes). Run build_site.py afterwards so
lookup.js picks up the same scores (its `sal` field).

  python3 export_saliency_webp.py
  python3 export_saliency_webp.py --quality 80
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

from PIL import Image

from corpus import canonical_ids

HERE = Path(__file__).resolve().parent
QA = HERE / "data" / "qa"
MAPS = QA / "saliency" / "maps"
ALT_MAPS = QA / "saliency_alts" / "maps"
SITE = HERE.parent / "site"
OUT = SITE / "saliency"
ALT_OUT = SITE / "saliency_alts"
ALTS_JSON = SITE / "data" / "poster_alts.json"
SCORES = QA / "saliency" / "saliency_score.csv"
SCORES_OUT = SITE / "data" / "saliency.json"


def alt_stems() -> set[str]:
    alts = json.loads(ALTS_JSON.read_text(encoding="utf-8"))
    stems = set()
    for pid, rows in alts.items():
        for row in rows:
            # row = [file_path, iso, measured]; the measured sheet uses MAPS.
            if row[2] == 1:
                continue
            name = row[0].lstrip("/")
            stems.add(f"{pid}_{name[:-4] if name.lower().endswith('.jpg') else name}")
    return stems


def to_webp(src: Path, quality: int) -> bytes:
    buf = io.BytesIO()
    Image.open(src).convert("L").save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


def sync(wanted: set[str], src_dir: Path, out_dir: Path, quality: int) -> tuple[int, int, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = missing = 0
    for stem in sorted(wanted):
        src = src_dir / f"{stem}.png"
        if not src.is_file():
            missing += 1
            continue
        data = to_webp(src, quality)
        dst = out_dir / f"{stem}.webp"
        if not dst.is_file() or dst.read_bytes() != data:
            dst.write_bytes(data)
            written += 1
    stale = [p for p in out_dir.glob("*.webp") if p.stem not in wanted]
    for p in stale:
        p.unlink()
    return written, missing, len(stale)


def write_scores(keep: set[str]) -> int:
    out: dict[str, list[float]] = {}
    with SCORES.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["id"] not in keep or r["id"] in out:
                continue
            out[r["id"]] = [
                round(float(r["peak_x"]), 3),
                round(float(r["peak_y"]), 3),
                round(float(r["top10pct_mass"]), 2),
            ]
    SCORES_OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return len(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", type=int, default=80)
    args = ap.parse_args()
    for d in (MAPS, ALT_MAPS):
        if not d.is_dir():
            raise SystemExit(f"falta {d} — corre el pipeline de saliencia (MSI-Net)")

    corpus = {str(i) for i in canonical_ids()}
    print(f"saliency.json: {write_scores(corpus):,} ids")
    jobs = [
        ("medidas", corpus, MAPS, OUT),
        ("alternativas", alt_stems(), ALT_MAPS, ALT_OUT),
    ]
    for label, wanted, src_dir, out_dir in jobs:
        written, missing, stale = sync(wanted, src_dir, out_dir, args.quality)
        n = len(list(out_dir.glob("*.webp")))
        mb = sum(p.stat().st_size for p in out_dir.glob("*.webp")) / 1e6
        print(
            f"{label}: {n:,}/{len(wanted):,} con mapa ({mb:.1f} MB) · "
            f"escritos {written:,} · sin PNG {missing:,} · borrados {stale:,}"
        )


if __name__ == "__main__":
    main()
