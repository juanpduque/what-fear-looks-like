#!/usr/bin/env python3
"""Rekognition DetectLabels + Image Properties on multi-poster variants.

One API call per image (GENERAL_LABELS + IMAGE_PROPERTIES). Does not touch
data/rekognition.csv (primary corpus). Writes:

  data/qa/rekognition_multi_variants.csv

  export AWS_PROFILE=sandbox
  python3 rekognition_multi_variants.py
  python3 rekognition_multi_variants.py --ids-file data/qa/poster_title_mismatch_consensus.csv
  python3 rekognition_multi_variants.py --include-primary
"""
from __future__ import annotations

import argparse
import csv
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from rekognition_enrich import ANIMAL, FIRE, PERSON, SILHOUETTE, WATER, WEAPON, _flag

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
MULTI = DATA / "posters_multi"
CONSENSUS = DATA / "qa" / "poster_title_mismatch_consensus.csv"
HM = DATA / "horror_movies.csv"
OUT = DATA / "qa" / "rekognition_multi_variants.csv"
REGION = "us-east-1"
MAX_BYTES = 5_000_000

FIELDS = [
    "id",
    "title",
    "year",
    "source",
    "stem",
    "file_path",
    "rek_labels",
    "rek_top",
    "rek_top_conf",
    "rek_weapon",
    "rek_animal",
    "rek_person",
    "rek_water",
    "rek_fire",
    "rek_silhouette",
    "rek_n_boxes",
    "rek_bright",
    "rek_sharp",
    "rek_contrast",
    "rek_colors",
    "latency_s",
    "error",
]

_print_lock = threading.Lock()
_write_lock = threading.Lock()
_rate_lock = threading.Lock()
_next_slot = 0.0


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def acquire(min_interval: float) -> None:
    global _next_slot
    with _rate_lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + min_interval
        wait = slot - now
    if wait > 0:
        time.sleep(wait)


def load_meta() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for path in (DATA / "posters.csv", HM, CONSENSUS):
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(float(r["id"]))
                except Exception:
                    continue
                cur = out.setdefault(pid, {})
                if r.get("title") and not cur.get("title"):
                    cur["title"] = r["title"]
                if r.get("year") and not cur.get("year"):
                    cur["year"] = r["year"]
                elif not cur.get("year"):
                    rd = (r.get("release_date") or "")[:4]
                    if rd.isdigit():
                        cur["year"] = rd
    return out


def load_ids(path: Path) -> list[int]:
    ids: list[int] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                ids.append(int(r["id"]))
            except Exception:
                pass
    return ids


def load_done(path: Path, force: bool) -> dict[tuple[int, str], dict]:
    if force or not path.exists():
        return {}
    out: dict[tuple[int, str], dict] = {}
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("error"):
                continue
            try:
                key = (int(r["id"]), str(r.get("stem") or ""))
            except Exception:
                continue
            out[key] = r
    return out


def write_rows(path: Path, rows: dict[tuple[int, str], dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for k in sorted(rows, key=lambda x: (x[0], x[1])):
                w.writerow(rows[k])


def detect_labels_props(client, path: Path, min_interval: float) -> dict:
    t0 = time.perf_counter()
    if not path.exists() or path.stat().st_size < 500:
        return {"error": "missing_jpg", "latency_s": round(time.perf_counter() - t0, 3)}
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        # light shrink via poster_ocr_rek_text helper if available
        try:
            from poster_ocr_rek_text import prepare_bytes

            data = prepare_bytes(path)
        except Exception:
            return {"error": "too_large", "latency_s": round(time.perf_counter() - t0, 3)}

    last = None
    for attempt in range(6):
        acquire(min_interval)
        try:
            lab = client.detect_labels(
                Image={"Bytes": data},
                MaxLabels=20,
                MinConfidence=50,
                Features=["GENERAL_LABELS", "IMAGE_PROPERTIES"],
                Settings={"ImageProperties": {"MaxDominantColors": 5}},
            )
            break
        except ClientError as e:
            last = e
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ThrottlingException", "ProvisionedThroughputExceededException"):
                time.sleep(min(20, 1.5 * (2**attempt)))
                continue
            return {
                "error": f"{code}: {e}"[:240],
                "latency_s": round(time.perf_counter() - t0, 3),
            }
    else:
        return {
            "error": f"{type(last).__name__}: {last}"[:240],
            "latency_s": round(time.perf_counter() - t0, 3),
        }

    labels = [(l["Name"], float(l["Confidence"]) / 100.0) for l in lab.get("Labels", [])]
    n_boxes = sum(len(l.get("Instances") or []) for l in lab.get("Labels", []))
    ip = lab.get("ImageProperties") or {}
    q = ip.get("Quality") or {}
    colors = ip.get("DominantColors") or []
    color_s = "|".join(
        f"{c.get('HexCode', '')}:{round(float(c.get('PixelPercent', 0)), 1)}"
        for c in colors[:5]
    )
    label_s = "|".join(f"{n}:{c:.2f}" for n, c in labels[:10])
    top_n, top_c = (labels[0][0], labels[0][1]) if labels else ("", 0.0)
    return {
        "rek_labels": label_s,
        "rek_top": top_n,
        "rek_top_conf": round(top_c, 4),
        "rek_weapon": _flag(labels, WEAPON),
        "rek_animal": _flag(labels, ANIMAL),
        "rek_person": _flag(labels, PERSON),
        "rek_water": _flag(labels, WATER),
        "rek_fire": _flag(labels, FIRE),
        "rek_silhouette": _flag(labels, SILHOUETTE),
        "rek_n_boxes": int(n_boxes),
        "rek_bright": round(float(q.get("Brightness") or 0), 2),
        "rek_sharp": round(float(q.get("Sharpness") or 0), 2),
        "rek_contrast": round(float(q.get("Contrast") or 0), 2),
        "rek_colors": color_s,
        "latency_s": round(time.perf_counter() - t0, 3),
        "error": "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--ids-file",
        default="",
        help="CSV with id column (default: consensus). Use --all-multi for full local posters_multi",
    )
    ap.add_argument(
        "--all-multi",
        action="store_true",
        help="Scan data/posters_multi for all local variant JPGs (full downloaded multi set)",
    )
    ap.add_argument("--include-primary", action="store_true")
    ap.add_argument("--ge2-only", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-interval", type=float, default=0.08)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    meta = load_meta()
    if args.all_multi:
        ids = sorted(
            int(d.name)
            for d in MULTI.iterdir()
            if d.is_dir() and d.name.isdigit() and any(d.glob("*.jpg"))
        )
        log(f"all-multi dirs with jpg: {len(ids)}")
    else:
        ids_path = Path(args.ids_file) if args.ids_file else CONSENSUS
        ids = load_ids(ids_path)
    if args.limit:
        ids = ids[: args.limit]

    jobs: list[tuple[int, str, str, Path]] = []
    for pid in ids:
        if args.include_primary:
            p = POSTERS / f"{pid}.jpg"
            if p.exists():
                jobs.append((pid, "primary", f"{pid}.jpg", p))
        d = MULTI / str(pid)
        if not d.is_dir():
            continue
        variants = sorted(d.glob("*.jpg"))
        if args.ge2_only and len(variants) < 2:
            continue
        for vp in variants:
            jobs.append((pid, "variant", vp.stem, vp))

    done = load_done(OUT, args.force)
    todo = [j for j in jobs if (j[0], j[2]) not in done]
    log(f"jobs={len(jobs)} todo={len(todo)} done={len(done)} workers={args.workers}")

    client = boto3.client(
        "rekognition",
        region_name=args.region,
        config=Config(retries={"max_attempts": 8, "mode": "adaptive"}),
    )

    rows = dict(done)
    t0 = time.time()
    ok = err = 0
    completed = 0

    def one(job: tuple[int, str, str, Path]) -> dict:
        pid, source, stem, path = job
        m = meta.get(pid, {})
        base = {
            "id": pid,
            "title": m.get("title") or "",
            "year": m.get("year") or "",
            "source": source,
            "stem": stem,
            "file_path": str(path.relative_to(DATA)) if path.exists() else str(path),
        }
        try:
            base.update(detect_labels_props(client, path, args.min_interval))
        except Exception as e:
            base["error"] = f"{type(e).__name__}: {e}"[:240]
            base["latency_s"] = ""
        return base

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(one, j): j for j in todo}
        for fut in as_completed(futs):
            row = fut.result()
            key = (int(row["id"]), str(row["stem"]))
            rows[key] = row
            completed += 1
            if row.get("error"):
                err += 1
            else:
                ok += 1
            if completed % 25 == 0 or completed == len(todo):
                write_rows(OUT, rows)
                rate = completed / max(1e-6, time.time() - t0)
                log(
                    f"[{completed}/{len(todo)}] ok={ok} err={err} {rate:.2f}/s "
                    f"id={row['id']} top={row.get('rek_top')}"
                )

    write_rows(OUT, rows)
    log(
        f"LISTO n={len(rows)} ok_run={ok} err={err} "
        f"elapsed={(time.time()-t0)/60:.1f}m → {OUT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
