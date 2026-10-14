#!/usr/bin/env python3
"""Image registry for the published posters: which image each film was measured on.

Metrics are stored per TMDB film id, but the image behind an id can change:
TMDB swaps the primary poster, ids get remapped, and apply_poster_primary_drift.py
replaces posters/{id}.jpg without re-running every measure. This records, for
each published film (corpus + comparable non-English), the image on disk and
the image the site shows, so mismatches are counted instead of guessed.

Per film:
  file_sha256, file_phash, file_w, file_h   posters/{id}.jpg (what the scripts measure)
  path_phash                                TMDB w500 of the poster_path the site shows
                                            (explorer.js, else horror_movies.csv), in memory
  phash_dist                                Hamming distance file vs path (0–64);
                                            <= SAME_MAX means the same artwork
  tmdb_current_path                         primary poster in the TMDB cache
                                            (fetch_tmdb_details.py)

pHash: 32x32 grayscale, 2-D DCT, top-left 8x8 against its median (64 bits, hex).
It survives resizing and re-encoding, so it matches the same artwork at
different resolutions; sha256 identifies the exact file.

  python3 build_poster_images.py [--limit N] [--workers 16] [--disk-workers 2]

Writes data/poster_images.csv (resumable: ids already written are skipped).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from scipy.fft import dctn

from corpus import canonical_ids
from export_world_faces import comparable_non_english

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
POSTERS = DATA / "posters"
SITE_DATA = HERE.parent / "site" / "data"
OUT = DATA / "poster_images.csv"
TMDB = DATA / "qa" / "tmdb_details" / "tmdb_details.jsonl"
IMG_BASE = "https://image.tmdb.org/t/p/w500"
SAME_MAX = 10
FIELDS = [
    "id",
    "lang",
    "poster_path",
    "tmdb_current_path",
    "file_sha256",
    "file_phash",
    "file_w",
    "file_h",
    "path_phash",
    "phash_dist",
    "error",
]


def phash(img: Image.Image) -> str:
    g = np.asarray(img.convert("L").resize((32, 32), Image.LANCZOS), dtype=np.float64)
    low = dctn(g, norm="ortho")[:8, :8].flatten()
    bits = low > np.median(low)
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def hash_file(pid: int) -> dict:
    row: dict = {}
    try:
        data = (POSTERS / f"{pid}.jpg").read_bytes()
        row["file_sha256"] = hashlib.sha256(data).hexdigest()
        with Image.open(io.BytesIO(data)) as im:
            row["file_w"], row["file_h"] = im.size
            row["file_phash"] = phash(im)
    except Exception as e:  # noqa: BLE001 - record and continue
        row["error"] = f"file: {e}"[:120]
    return row


def hash_path(path: str, session) -> dict:
    if not path:
        return {}
    err = ""
    for _ in range(3):
        try:
            resp = session.get(IMG_BASE + path, timeout=30)
            resp.raise_for_status()
            with Image.open(io.BytesIO(resp.content)) as im:
                return {"path_phash": phash(im)}
        except Exception as e:  # noqa: BLE001
            err = f"path: {e}"[:120]
    return {"error": err}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16, help="parallel TMDB downloads")
    ap.add_argument(
        "--disk-workers", type=int, default=2, help="parallel reads of posters/ (slow on a USB HDD)"
    )
    args = ap.parse_args()

    langs = {pid: "en" for pid in canonical_ids()}
    langs.update(comparable_non_english())
    # What the site shows: explorer.js for the corpus (horror_movies.csv lacks
    # the path for ~9.5k corpus films that got it from a backfill), else
    # horror_movies.csv (world films).
    paths = {}
    with (DATA / "horror_movies.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            paths[int(r["id"])] = r.get("poster_path") or ""
    text = (SITE_DATA / "explorer.js").read_text(encoding="utf-8")
    for row in json.loads(text[text.index("[") : text.rindex("]") + 1]):
        if row[2]:
            paths[int(row[7])] = row[2]
    current = {}
    for line in TMDB.open(encoding="utf-8"):
        rec = json.loads(line)
        current[int(rec["id"])] = rec.get("poster_path")
    done = set()
    if OUT.exists():
        # Keep complete rows; redo rows whose site image is now known but unhashed.
        with OUT.open(newline="", encoding="utf-8") as f:
            kept = [r for r in csv.DictReader(f) if r["path_phash"] or not paths.get(int(r["id"]))]
        with OUT.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(kept)
        done = {int(r["id"]) for r in kept}
    todo = [pid for pid in sorted(langs) if pid not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(langs):,} published films, {len(done):,} done, {len(todo):,} to hash", flush=True)

    new_file = not OUT.exists()
    session = requests.Session()
    with (
        OUT.open("a", newline="", encoding="utf-8") as f,
        ThreadPoolExecutor(args.workers) as net,
        ThreadPoolExecutor(args.disk_workers) as disk,
    ):
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        jobs = [
            (pid, net.submit(hash_path, paths.get(pid, ""), session), disk.submit(hash_file, pid))
            for pid in todo
        ]
        for i, (pid, from_path, from_file) in enumerate(jobs, 1):
            a, b = from_path.result(), from_file.result()
            row = {
                "id": pid,
                "lang": langs[pid],
                "poster_path": paths.get(pid, ""),
                "tmdb_current_path": current.get(pid) or "",
                **b,
                **{k: v for k, v in a.items() if k != "error"},
                "error": "; ".join(x for x in (b.get("error"), a.get("error")) if x),
            }
            if row.get("file_phash") and row.get("path_phash"):
                row["phash_dist"] = hamming(row["file_phash"], row["path_phash"])
            w.writerow(row)
            if i % 1000 == 0 or i == len(todo):
                f.flush()
                print(f"  {i:,}/{len(todo):,}", flush=True)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
