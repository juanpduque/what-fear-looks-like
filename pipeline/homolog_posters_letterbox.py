#!/usr/bin/env python3
"""Homologate posters to a fixed canvas with letterbox (contain + pad).

Prefer upscaled source when present:
  posters_original_up/{id}.jpg  else  posters_original/{id}.jpg
→ posters_homolog/{id}.jpg  (default 1000×1500, black bars)

  python3 homolog_posters_letterbox.py
  python3 homolog_posters_letterbox.py --width 1000 --height 1500 --workers 8
"""
from __future__ import annotations

import argparse
import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

DATA = Path(__file__).resolve().parent / "data"
QA = DATA / "qa"
IDS = QA / "corpus_filter_qa_ids.txt"
IDS_CSV = QA / "corpus_filter_qa_ids.csv"
ORIG = DATA / "posters_original"
UP = DATA / "posters_original_up"
OUT = DATA / "posters_homolog"
MANIFEST = QA / "posters_homolog_manifest.csv"


def load_ids() -> list[int]:
    if IDS.exists():
        return [int(x) for x in IDS.read_text().splitlines() if x.strip()]
    return [int(r["id"]) for r in csv.DictReader(IDS_CSV.open())]


def letterbox(im: Image.Image, tw: int, th: int, fill=(0, 0, 0)) -> Image.Image:
    im = im.convert("RGB")
    w, h = im.size
    scale = min(tw / w, th / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = im.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (tw, th), fill)
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return canvas


def process_one(pid: int, tw: int, th: int, force: bool) -> dict:
    out = OUT / f"{pid}.jpg"
    up = UP / f"{pid}.jpg"
    orig = ORIG / f"{pid}.jpg"
    src = up if up.exists() and up.stat().st_size > 1000 else orig
    row = {
        "id": pid,
        "source": "up" if src == up else ("orig" if src == orig else "missing"),
        "status": "",
        "in_w": "",
        "in_h": "",
        "out_w": tw,
        "out_h": th,
        "error": "",
    }
    if not src.exists():
        row["status"] = "missing"
        row["error"] = "no source"
        return row
    if out.exists() and out.stat().st_size > 1000 and not force:
        row["status"] = "exists"
        try:
            with Image.open(src) as im:
                row["in_w"], row["in_h"] = im.size
        except Exception:
            pass
        return row
    try:
        with Image.open(src) as im:
            row["in_w"], row["in_h"] = im.size
            out_im = letterbox(im, tw, th)
        tmp = out.with_suffix(".partial.jpg")
        out_im.save(tmp, format="JPEG", quality=92, optimize=True)
        tmp.replace(out)
        row["status"] = "ok"
    except Exception as e:
        row["status"] = "error"
        row["error"] = str(e)[:300]
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--width", type=int, default=1000)
    ap.add_argument("--height", type=int, default=1500)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    ids = load_ids()
    if args.limit:
        ids = ids[: args.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    print(
        f"homolog n={len(ids)} canvas={args.width}x{args.height} "
        f"orig={ORIG} up={UP} out={OUT}",
        flush=True,
    )

    rows: list[dict] = []
    ok = exists = miss = err = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(process_one, pid, args.width, args.height, args.force): pid
            for pid in ids
        }
        done = 0
        for fut in as_completed(futs):
            done += 1
            row = fut.result()
            rows.append(row)
            st = row["status"]
            if st == "ok":
                ok += 1
            elif st == "exists":
                exists += 1
            elif st == "missing":
                miss += 1
            else:
                err += 1
            if done % 500 == 0 or done == len(futs):
                print(
                    f"  {done}/{len(futs)} ok={ok} exists={exists} miss={miss} err={err} "
                    f"{time.time()-t0:.0f}s",
                    flush=True,
                )

    fields = ["id", "source", "status", "in_w", "in_h", "out_w", "out_h", "error"]
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sorted(rows, key=lambda x: int(x["id"])):
            w.writerow(r)
    print(f"LISTO ok={ok} exists={exists} miss={miss} err={err} → {OUT}\nmanifest={MANIFEST}")


if __name__ == "__main__":
    main()
