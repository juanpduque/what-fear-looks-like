#!/usr/bin/env python3
"""Stage posters for ocr_qwen_hard: homolog > original_up > original > w342."""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

PREFIX = os.environ.get("PREFIX", "ocr_qwen_hard")
BUCKET = os.environ.get("BUCKET", "aof-owlv2-102516364259")
MAX_N = int(os.environ.get("MAX_N", "120"))

qa = Path(f"data/qa/{PREFIX}")
ids_path = qa / "sample_ids.txt"
ids = [int(x) for x in ids_path.read_text().split() if x.strip()]
stage = Path(f"data/qa/_{PREFIX}_stage")
dst = stage / "posters"
dst.mkdir(parents=True, exist_ok=True)
(stage / "qa").mkdir(parents=True, exist_ok=True)


def copy_file(src: Path, d: Path) -> None:
    shutil.copy2(src, d)


def pull_s3(key_prefix: str, pid: int, d: Path) -> bool:
    r = subprocess.run(
        ["aws", "s3", "cp", f"s3://{BUCKET}/{key_prefix}/{pid}.jpg", str(d)],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and d.exists() and d.stat().st_size > 1000


def try_local(dir_name: str, pid: int, d: Path) -> bool:
    s = Path(f"data/{dir_name}") / f"{pid}.jpg"
    if s.exists() and s.stat().st_size > 1000:
        copy_file(s, d)
        return True
    return False


CHAIN = [
    ("homolog", "posters_homolog", "posters_homolog"),
    ("original_up", "posters_original_up", "posters_original_up"),
    ("original", "posters_original", "posters_original"),
    ("w342", "posters", "posters"),
]

rows = []
ok_ids = []
counts = {lab: 0 for lab, _, _ in CHAIN}
miss = []

for pid in ids:
    d = dst / f"{pid}.jpg"
    if d.exists():
        d.unlink()
    chosen = None
    for label, local_dir, s3_pref in CHAIN:
        if try_local(local_dir, pid, d):
            chosen = label
            break
        if pull_s3(s3_pref, pid, d):
            chosen = label
            break
    if chosen is None:
        miss.append(pid)
        print(f"MISSING all sources id={pid}", flush=True)
        continue
    counts[chosen] += 1
    ok_ids.append(pid)
    note = ""
    if chosen == "w342":
        note = "NOT_HOMOLOG; best available is w342 only"
    rows.append({"id": pid, "source": chosen, "note": note})
    print(f"staged id={pid} source={chosen}", flush=True)

print(
    "source_counts "
    + " ".join(f"{k}={v}" for k, v in counts.items())
    + f" miss={len(miss)} of={len(ids)}",
    flush=True,
)

if miss:
    raise SystemExit(f"incomplete stage: missing {miss}")
if not ok_ids:
    raise SystemExit("no posters staged")
if len(ok_ids) > MAX_N:
    raise SystemExit(f"refuse staging {len(ok_ids)} > {MAX_N}")

src_csv = qa / "poster_sources.csv"
with src_csv.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["id", "source", "note"])
    w.writeheader()
    w.writerows(rows)
print(f"wrote {src_csv}", flush=True)

# Filter posters.csv without pandas
ok_set = set(ok_ids)
with open("data/posters.csv", encoding="utf-8", newline="") as fin, open(
    stage / "posters.csv", "w", encoding="utf-8", newline=""
) as fout:
    reader = csv.DictReader(fin)
    fieldnames = reader.fieldnames or ["id", "title", "year"]
    writer = csv.DictWriter(fout, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    n = 0
    for row in reader:
        try:
            pid = int(row["id"])
        except (KeyError, ValueError):
            continue
        if pid in ok_set:
            writer.writerow(row)
            n += 1
print(f"posters.csv subset rows={n} ids={len(ok_ids)}", flush=True)

shutil.copy2(ids_path, stage / "qa" / "sample_ids.txt")
meta = qa / "sample_meta.csv"
if meta.exists():
    shutil.copy2(meta, stage / "qa" / "sample_meta.csv")
shutil.copy2(src_csv, stage / "qa" / "poster_sources.csv")
print(f"staged jpgs={len(ok_ids)}", flush=True)
