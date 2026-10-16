#!/usr/bin/env python3
"""Per-metric image ledger: the sha256 of the file each metric was measured on.

poster_images.csv records which image is on disk for each published film, but
not which image each metric saw. After the 2026-10-14 restoration that matters:
color, faces and CLIP of 1,440 world posters were re-measured on the restored
file, their segmentation and weapon boxes were not. This keeps one row per
published film (corpus + comparable non-English) and one sha256 column per
metric; empty means the metric has no row for that film.

  python3 metric_images.py --seed    # build data/metric_images.csv from today's files
  python3 metric_images.py           # check: re-hash posters/, list stale metrics

--seed assumes every metric was measured on the file now in posters/, except
what the restoration manifest (posters_site_restore/manifest.csv) says
otherwise: for restored world posters, segmentation and weapon boxes keep the
old file's sha256. That assumption was checked on samples (docs/METRIC_AGREEMENTS.md),
not per film.

The check writes data/qa/metric_images_stale.csv (id, metric, ledger, file) for
every metric whose sha256 differs from the file in posters/ today. Scripts that
re-measure call record(metric, ids) so the ledger follows the new file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
POSTERS = DATA / "posters"
OUT = DATA / "metric_images.csv"
STALE = DATA / "qa" / "metric_images_stale.csv"
# the restore folders sit next to the real posters/ (data/posters is a symlink)
MANIFEST = POSTERS.resolve().parent / "posters_site_restore" / "manifest.csv"


def _csv_ids(name: str) -> set[int]:
    with (DATA / name).open(newline="", encoding="utf-8") as f:
        return {int(float(r["id"])) for r in csv.DictReader(f) if r.get("id")}


def _json_ids(*names: str) -> set[int]:
    out: set[int] = set()
    for name in names:
        out |= {int(k) for k, v in json.loads((DATA / name).read_text("utf-8")).items() if v}
    return out


def _npz_ids(name: str) -> set[int]:
    import numpy as np

    return {int(x) for x in np.load(DATA / name)["ids"]}


# metric -> where its rows live (membership only; values are not read)
METRICS = {
    "color": lambda: _csv_ids("posters.csv"),
    "faces": lambda: _csv_ids("faces_v2.csv"),
    "clip_embed": lambda: _npz_ids("clip_embeddings.npz"),
    "census": lambda: _csv_ids("census.csv"),
    "typography": lambda: _csv_ids("typography.csv"),
    "medium": lambda: _csv_ids("medium.csv"),
    "attributes": lambda: _csv_ids("attributes.csv"),
    "segmentation": lambda: _csv_ids("segmentation.csv"),
    "rekognition": lambda: _csv_ids("rekognition.csv"),
    "creature_boxes": lambda: _json_ids("creature_boxes.json", "qa/creature_boxes_world.json"),
    "weapon_boxes": lambda: _json_ids("weapon_boxes.json"),
}
# measured on the pre-restore file for restored world posters
NOT_REMEASURED = ("segmentation", "weapon_boxes")
FIELDS = ["id", *METRICS]


def published_ids() -> list[int]:
    from corpus import canonical_ids
    from export_world_faces import comparable_non_english

    return sorted(set(canonical_ids()) | set(comparable_non_english()))


def file_sha(pid: int) -> str:
    try:
        return hashlib.sha256((POSTERS / f"{pid}.jpg").read_bytes()).hexdigest()
    except OSError:
        return ""


def hash_all(ids, workers: int) -> dict[int, str]:
    ids = list(ids)
    with ThreadPoolExecutor(workers) as ex:
        return dict(zip(ids, ex.map(file_sha, ids)))


def load() -> dict[int, dict]:
    with OUT.open(newline="", encoding="utf-8") as f:
        return {int(r["id"]): r for r in csv.DictReader(f)}


def save(rows: dict[int, dict]) -> None:
    # data/metric_images.csv is a symlink to the backup disk: write next to the target
    out = OUT.resolve()
    tmp = out.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for pid in sorted(rows):
            w.writerow(rows[pid])
    tmp.replace(out)


def record(metric: str, ids, workers: int = 4) -> None:
    """Set metric's sha256 to today's posters/ file for these ids."""
    if metric not in METRICS:
        raise KeyError(metric)
    if not OUT.exists():
        print(f"  {OUT.name} missing; run metric_images.py --seed")
        return
    rows = load()
    shas = hash_all(ids, workers)
    for pid, sha in shas.items():
        row = rows.setdefault(pid, {"id": pid})
        row[metric] = sha
    save(rows)
    print(f"  {OUT.name}: {metric} recorded for {len(shas):,} ids")


def seed(workers: int) -> None:
    ids = published_ids()
    print(f"hashing {len(ids):,} posters/ files ...", flush=True)
    shas = hash_all(ids, workers)
    old = {}
    with MANIFEST.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["status"] == "ok" and r["lang"] != "en":
                old[int(r["id"])] = r["old_sha256"]
    members = {m: load_ids() for m, load_ids in METRICS.items()}
    rows = {}
    for pid in ids:
        row = {"id": pid}
        for m, have in members.items():
            if pid not in have:
                row[m] = ""
            elif pid in old and m in NOT_REMEASURED:
                row[m] = old[pid]
            else:
                row[m] = shas[pid]
        rows[pid] = row
    save(rows)
    print(f"wrote {OUT} ({len(rows):,} films, {len(old):,} restored world posters)")
    for m, have in members.items():
        n = sum(1 for r in rows.values() if r[m])
        print(f"  {m:15s} {n:6,}  ({len(have - set(ids)):,} rows outside the published set)")


def check(workers: int) -> int:
    rows = load()
    print(f"hashing {len(rows):,} posters/ files ...", flush=True)
    shas = hash_all(rows, workers)
    stale = []
    for pid, row in rows.items():
        for m in METRICS:
            if row.get(m) and row[m] != shas[pid]:
                stale.append({"id": pid, "metric": m, "ledger": row[m], "file": shas[pid]})
    STALE.parent.mkdir(parents=True, exist_ok=True)
    with STALE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "metric", "ledger", "file"])
        w.writeheader()
        w.writerows(stale)
    missing = sum(1 for s in shas.values() if not s)
    by_metric = Counter(s["metric"] for s in stale)
    print(f"{len(rows):,} films, {missing:,} without a file in posters/")
    for m in METRICS:
        print(f"  {m:15s} stale {by_metric.get(m, 0):6,}")
    print(f"wrote {STALE}")
    return 1 if stale else 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--seed", action="store_true", help="rebuild the ledger from today's files")
    ap.add_argument("--workers", type=int, default=4, help="parallel reads of posters/")
    args = ap.parse_args()
    if args.seed:
        seed(args.workers)
    else:
        raise SystemExit(check(args.workers))


if __name__ == "__main__":
    main()
