#!/usr/bin/env python3
"""OWLv2 creature + weapon boxes on TMDB alternative sheets.

Keyed by (id, file_path). Does not rewrite creature_boxes.json / weapon_boxes.json
of the measured cover.

  python3 owl_alts.py --jobs-file data/qa/alts_comp_catalog/jobs.csv --out /tmp/owl_alts.csv
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

from owlv2_creature_boxes import (
    CREATURE_QUERIES,
    WEAPON_QUERIES,
    filter_boxes,
    pick_device,
)

TMDB = "https://image.tmdb.org/t/p/w500"
FIELDS = [
    "id",
    "file_path",
    "tmdb_hash",
    "sha256",
    "creature_boxes",
    "weapon_boxes",
    "n_creature",
    "n_weapon",
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


def empty_row(pid: int, fp: str, **extra) -> dict:
    row = {k: "" for k in FIELDS}
    row.update(
        id=pid,
        file_path=fp,
        tmdb_hash=tmdb_hash(fp),
        creature_boxes="[]",
        weapon_boxes="[]",
        n_creature=0,
        n_weapon=0,
    )
    row.update(extra)
    return row


def postprocess(processor, outputs, min_score, h, w, device, all_labels):
    target = torch.tensor([[h, w]], device=device)
    if hasattr(processor, "post_process_grounded_object_detection"):
        try:
            return processor.post_process_grounded_object_detection(
                outputs=outputs,
                threshold=min_score,
                target_sizes=target,
                text_labels=[all_labels],
            )[0]
        except TypeError:
            return processor.post_process_grounded_object_detection(
                outputs=outputs,
                threshold=min_score,
                target_sizes=target,
            )[0]
    results = processor.post_process_object_detection(
        outputs=outputs,
        threshold=min_score,
        target_sizes=target,
    )[0]
    labs = results.get("labels")
    if labs is not None and results.get("text_labels") is None:
        results["text_labels"] = [all_labels[int(i)] for i in labs.detach().cpu().tolist()]
    return results


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache-dir", default="/tmp/alts_owl")
    ap.add_argument("--checkpoint-every", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--min-score", type=float, default=0.2)
    ap.add_argument("--model-id", default="google/owlv2-base-patch16")
    ap.add_argument("--keep-jpg", action="store_true")
    args = ap.parse_args()

    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    device = pick_device(args.device)
    print(f"loading {args.model_id} on {device}…", flush=True)
    processor = Owlv2Processor.from_pretrained(args.model_id)
    model = Owlv2ForObjectDetection.from_pretrained(args.model_id).to(device).eval()

    creature_labels = list(CREATURE_QUERIES)
    weapon_labels = list(WEAPON_QUERIES)
    all_labels = creature_labels + weapon_labels
    query_map = dict(CREATURE_QUERIES)
    query_map.update(WEAPON_QUERIES)
    text = [[query_map[l] for l in all_labels]]
    creature_set = set(creature_labels)
    weapon_set = set(weapon_labels)

    jobs = load_jobs(Path(args.jobs_file), args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    done = load_done(out)
    todo = [j for j in jobs if j not in done]
    print(
        f"jobs={len(jobs)} todo={len(todo)} done={len(done)} device={device} "
        f"queries={len(all_labels)}",
        flush=True,
    )

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
            img = Image.open(dest).convert("RGB")
            w, h = img.size
            inputs = processor(text=text, images=img, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = model(**inputs)
            results = postprocess(processor, outputs, args.min_score, h, w, device, all_labels)
            boxes = results["boxes"].detach().cpu().tolist()
            scores = results["scores"].detach().cpu().tolist()
            if results.get("text_labels") is not None:
                labs = [str(x) for x in results["text_labels"]]
            else:
                labs = [all_labels[int(i)] for i in results["labels"].detach().cpu().tolist()]
            c_idx = [i for i, lab in enumerate(labs) if lab in creature_set]
            w_idx = [i for i, lab in enumerate(labs) if lab in weapon_set]
            c_boxes = filter_boxes(
                [boxes[i] for i in c_idx],
                [scores[i] for i in c_idx],
                [labs[i] for i in c_idx],
                w,
                h,
                min_score=args.min_score,
            )
            w_boxes = filter_boxes(
                [boxes[i] for i in w_idx],
                [scores[i] for i in w_idx],
                [labs[i] for i in w_idx],
                w,
                h,
                min_score=args.min_score,
            )
            writer.writerow(
                empty_row(
                    pid,
                    fp,
                    sha256=hashlib.sha256(data).hexdigest(),
                    creature_boxes=json.dumps(c_boxes, ensure_ascii=False, separators=(",", ":")),
                    weapon_boxes=json.dumps(w_boxes, ensure_ascii=False, separators=(",", ":")),
                    n_creature=len(c_boxes),
                    n_weapon=len(w_boxes),
                    status="ok",
                    error="",
                )
            )
            n_ok += 1
        except Exception as e:
            n_err += 1
            writer.writerow(
                empty_row(pid, fp, status="error", error=f"{type(e).__name__}: {e}"[:240])
            )
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
            sec = (time.time() - t0) / max(n_done, 1)
            print(
                f"  {n_done:,}/{len(todo):,} ok={n_ok} 404={n_404} err={n_err} "
                f"{rate:.2f}/s ({sec:.1f}s/img)",
                flush=True,
            )
    f_out.close()
    print(f"LISTO ok={n_ok} 404={n_404} err={n_err}", flush=True)
    if n_ok == 0 and n_err > 0:
        return 2
    if n_err >= 50 and n_err >= max(n_ok, 1) * 5:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
