#!/usr/bin/env python3
"""ViTPose + YOLO on TMDB alternative sheets.

Keyed by (id, file_path). Does not rewrite pose_score_kpts.csv of the measured cover.

  python3 vitpose_alts.py --jobs-file data/qa/alts_comp_catalog/jobs.csv --out /tmp/pose.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path

import requests
import torch
from PIL import Image

from vitpose_dynamism_score import (
    MAX_PERSONS,
    compute_metrics,
    encode_kpts,
    primary_index,
)

TMDB = "https://image.tmdb.org/t/p/w500"
FIELDS = [
    "id",
    "file_path",
    "tmdb_hash",
    "sha256",
    "n_persons",
    "kpt_bbox_area_frac",
    "limb_asymmetry",
    "mean_kpt_confidence",
    "img_w",
    "img_h",
    "box",
    "keypoints",
    "persons",
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


def load_done(path: Path) -> set[tuple[int, str]]:
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
            if fp and (r.get("status") or "") in {"ok", "missing_404"}:
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
    row.update(id=pid, file_path=fp, tmdb_hash=tmdb_hash(fp), persons="[]")
    row.update(extra)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache-dir", default="/tmp/alts_pose")
    ap.add_argument("--checkpoint-every", type=int, default=25)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep-jpg", action="store_true")
    args = ap.parse_args()

    from ultralytics import YOLO
    from transformers import AutoProcessor, VitPoseForPoseEstimation

    print("loading YOLOv8n...", flush=True)
    yolo = YOLO("yolov8n.pt")
    print("loading ViTPose...", flush=True)
    processor = AutoProcessor.from_pretrained("usyd-community/vitpose-base-simple")
    model = VitPoseForPoseEstimation.from_pretrained("usyd-community/vitpose-base-simple").eval()

    jobs = load_jobs(Path(args.jobs_file), args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    done = load_done(out)
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
        dest = cache / f"{pid}_{tmdb_hash(fp)}.jpg"
        try:
            data, st = fetch(fp, dest)
            if st == "missing_404" or data is None:
                writer.writerow(empty_row(pid, fp, status="missing_404", error="missing_404"))
                n_404 += 1
                n_done += 1
                continue
            sha = hashlib.sha256(data).hexdigest()
            img = Image.open(dest).convert("RGB")
            w, h = img.size
            yres = yolo(str(dest), classes=[0], verbose=False)
            boxes = yres[0].boxes.xyxy.cpu().numpy().tolist() if yres[0].boxes is not None else []
            row = empty_row(
                pid, fp, sha256=sha, n_persons=len(boxes), img_w=w, img_h=h,
                status="ok", error="",
            )
            if boxes:
                boxes.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
                use = boxes[:MAX_PERSONS]
                inputs = processor(img, boxes=[use], return_tensors="pt")
                with torch.no_grad():
                    outputs = model(**inputs)
                results = processor.post_process_pose_estimation(outputs, boxes=[use])
                detected = results[0]
                packed = []
                for box, person in zip(use, detected):
                    kpts = person["keypoints"].numpy()
                    scores = person["scores"].numpy()
                    met = compute_metrics(kpts, scores, box)
                    packed.append({
                        "box": [round(float(c), 1) for c in box],
                        "keypoints": encode_kpts(kpts, scores),
                        "metrics": met,
                    })
                mets = [p["metrics"] for p in packed]
                idx = primary_index(use, mets, w, h)
                chosen = packed[idx]
                row.update({k: (v if v is not None else "") for k, v in chosen["metrics"].items()})
                row["box"] = json.dumps(chosen["box"])
                row["keypoints"] = json.dumps(chosen["keypoints"])
                row["persons"] = json.dumps(
                    [
                        {
                            "box": p["box"],
                            "keypoints": p["keypoints"],
                            "conf": p["metrics"].get("mean_kpt_confidence"),
                        }
                        for p in packed
                    ],
                    separators=(",", ":"),
                )
            writer.writerow(row)
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
            print(
                f"  {n_done:,}/{len(todo):,} ok={n_ok} 404={n_404} err={n_err} {rate:.2f}/s",
                flush=True,
            )
    f_out.close()
    print(f"LISTO ok={n_ok} 404={n_404} err={n_err} have={len(done)+n_ok+n_404}", flush=True)
    if n_err >= 50 and n_err >= max(n_ok, 1) * 5:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
