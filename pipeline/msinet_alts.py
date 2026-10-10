#!/usr/bin/env python3
"""MSI-Net saliency maps on TMDB alternative sheets.

Keyed by (id, file_path). Maps go to maps/{id}_{stem}.png — never maps/{id}.png
(the measured cover). Does not rewrite saliency_score.csv of the essay.

  python3 msinet_alts.py --jobs-file jobs.csv --out saliency.csv --maps-dir maps
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import time
from pathlib import Path

import numpy as np
import requests

from msinet_saliency_score import load_msinet, predict_saliency, saliency_to_uint8_png

TMDB = "https://image.tmdb.org/t/p/w500"
FIELDS = [
    "id",
    "file_path",
    "tmdb_hash",
    "sha256",
    "peak_x",
    "peak_y",
    "top10pct_mass",
    "mean_saliency",
    "map_w",
    "map_h",
    "map_path",
    "status",
    "error",
]


def tmdb_path(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("/") and raw.lower().endswith(".jpg"):
        return raw
    name = Path(raw).name
    return f"/{name}" if name.lower().endswith(".jpg") else ""


def tmdb_hash(file_path: str) -> str:
    name = Path(str(file_path or "").lstrip("/")).name
    return name[:-4] if name.lower().endswith(".jpg") else name


def load_jobs(path: Path, limit: int) -> list[tuple[int, str]]:
    jobs: list[tuple[int, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if not fp:
                continue
            jobs.append((pid, fp))
            if limit and len(jobs) >= limit:
                break
    return jobs


def load_done(path: Path, maps_dir: Path) -> set[tuple[int, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    out: set[tuple[int, str]] = set()
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            fp = tmdb_path(r.get("file_path") or "")
            st = r.get("status") or ""
            if not fp:
                continue
            if st == "missing_404":
                out.add((pid, fp))
                continue
            if st != "ok":
                continue
            png = maps_dir / f"{pid}_{tmdb_hash(fp)}.png"
            if png.is_file() and png.stat().st_size > 10:
                out.add((pid, fp))
    return out


def fetch(fp: str, dest: Path) -> tuple[bytes | None, str]:
    if dest.exists() and dest.stat().st_size > 500:
        return dest.read_bytes(), "ok"
    r = requests.get(TMDB + fp, timeout=60)
    if r.status_code == 404:
        return None, "missing_404"
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return r.content, "ok"


def empty_row(pid: int, fp: str, **extra) -> dict:
    row = {k: "" for k in FIELDS}
    row.update(id=pid, file_path=fp, tmdb_hash=tmdb_hash(fp))
    row.update(extra)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--maps-dir", required=True)
    ap.add_argument("--cache-dir", default="/tmp/alts_msinet")
    ap.add_argument("--checkpoint-every", type=int, default=25)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep-jpg", action="store_true")
    args = ap.parse_args()

    print("loading MSI-Net...", flush=True)
    model = load_msinet()
    print("MSI-Net loaded", flush=True)

    jobs = load_jobs(Path(args.jobs_file), args.limit)
    out = Path(args.out)
    maps_dir = Path(args.maps_dir)
    cache = Path(args.cache_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    maps_dir.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    done = load_done(out, maps_dir)
    todo = [j for j in jobs if j not in done]
    print(f"jobs={len(jobs)} todo={len(todo)} done={len(done)}", flush=True)

    new_file = not out.exists() or out.stat().st_size == 0
    f_out = out.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_out, fieldnames=FIELDS, extrasaction="ignore")
    if new_file:
        writer.writeheader()
        f_out.flush()

    t0 = time.time()
    n_ok = n_404 = n_err = n_done = 0
    for pid, fp in todo:
        stem = tmdb_hash(fp)
        dest = cache / f"{pid}_{stem}.jpg"
        png_name = f"{pid}_{stem}.png"
        try:
            data, st = fetch(fp, dest)
            if st == "missing_404" or data is None:
                writer.writerow(empty_row(pid, fp, status="missing_404", error="missing_404"))
                n_404 += 1
                n_done += 1
                continue
            sha = hashlib.sha256(data).hexdigest()
            sal = predict_saliency(model, dest)
            total = float(sal.sum())
            flat = sal.flatten()
            k = max(1, int(0.10 * flat.size))
            top10_mass = float(np.sort(flat)[-k:].sum() / total) if total > 0 else 0.0
            peak_y, peak_x = np.unravel_index(np.argmax(sal), sal.shape)
            png_path = maps_dir / png_name
            saliency_to_uint8_png(sal).save(png_path, format="PNG", optimize=True)
            writer.writerow(
                empty_row(
                    pid,
                    fp,
                    sha256=sha,
                    peak_x=round(float(peak_x / sal.shape[1]), 4),
                    peak_y=round(float(peak_y / sal.shape[0]), 4),
                    top10pct_mass=round(top10_mass, 4),
                    mean_saliency=round(float(sal.mean()), 4),
                    map_w=int(sal.shape[1]),
                    map_h=int(sal.shape[0]),
                    map_path=f"maps/{png_name}",
                    status="ok",
                    error="",
                )
            )
            n_ok += 1
        except Exception as e:
            n_err += 1
            writer.writerow(empty_row(pid, fp, status="error", error=f"{type(e).__name__}: {e}"[:240]))
            if n_err <= 8:
                print(f"  FAIL {pid} {fp}: {e}", flush=True)
        finally:
            if not args.keep_jpg:
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
        n_done += 1
        if n_done % args.checkpoint_every == 0 or n_done == len(todo):
            f_out.flush()
            rate = n_done / max(time.time() - t0, 1e-9)
            eta_s = (len(todo) - n_done) / rate if rate > 0 else 0
            print(
                f"  {n_done:,}/{len(todo):,} ok={n_ok} 404={n_404} err={n_err} "
                f"{rate:.2f}/s eta_h={eta_s/3600:.2f}",
                flush=True,
            )
    f_out.close()
    print(f"LISTO ok={n_ok} 404={n_404} err={n_err}", flush=True)
    if n_err >= 50 and n_err >= max(n_ok, 1) * 5:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
