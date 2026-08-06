#!/usr/bin/env python3
"""OCR-score TMDB multi-poster variants vs catalog title (Rekognition DetectText).

For consensus title-mismatches with local posters_multi/{id}/*.jpg:
  1) DetectText each variant (+ current posters/{id}.jpg as baseline)
  2) score = max(overlap(OCR, title), overlap(OCR, original_title))
  3) propose swap when best variant beats current by margin

Uses AWS Rekognition (no GPU EC2). Writes:
  data/qa/multi_poster_variant_ocr_scores.csv
  data/qa/multi_poster_variant_ocr_swaps.csv

  export AWS_PROFILE=sandbox
  python3 score_multi_poster_variants_ocr.py
  python3 score_multi_poster_variants_ocr.py --min-gain 0.25 --min-best 0.4
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

from ocr_metrics import title_fuzzy_score, title_overlap_score
from poster_ocr_rek_text import prepare_bytes

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
MULTI = DATA / "posters_multi"
HM = DATA / "horror_movies.csv"
CONSENSUS = DATA / "qa" / "poster_title_mismatch_consensus.csv"
OUT_SCORES = DATA / "qa" / "multi_poster_variant_ocr_scores.csv"
OUT_SWAPS = DATA / "qa" / "multi_poster_variant_ocr_swaps.csv"
REGION = "us-east-1"

SCORE_FIELDS = [
    "id",
    "title",
    "original_title",
    "year",
    "source",  # primary | variant
    "file_path",
    "stem",
    "ocr_chars",
    "n_lines",
    "overlap_title",
    "overlap_original",
    "overlap_max",
    "fuzzy_title",
    "fuzzy_original",
    "fuzzy_max",
    "latency_s",
    "error",
    "ocr_preview",
]

SWAP_FIELDS = [
    "id",
    "title",
    "original_title",
    "year",
    "current_stem",
    "current_overlap",
    "current_fuzzy",
    "best_stem",
    "best_file_path",
    "best_overlap",
    "best_fuzzy",
    "gain_overlap",
    "gain_fuzzy",
    "n_variants",
    "propose",
    "reason",
]

_print_lock = threading.Lock()
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
    if HM.exists():
        with HM.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(float(r["id"]))
                except Exception:
                    continue
                rd = (r.get("release_date") or "")[:4]
                out[pid] = {
                    "title": (r.get("title") or "").strip(),
                    "original_title": (r.get("original_title") or "").strip(),
                    "year": int(rd) if rd.isdigit() else "",
                }
    # fill from consensus / posters.csv / multi_poster_catalog if missing
    for extra in (
        CONSENSUS,
        DATA / "posters.csv",
        DATA / "multi_poster_catalog.csv",
    ):
        if not extra.exists():
            continue
        with extra.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(float(r["id"]))
                except Exception:
                    continue
                cur = out.setdefault(pid, {})
                for k in ("title", "original_title", "year"):
                    if r.get(k) and not cur.get(k):
                        v = r[k]
                        if k == "year":
                            try:
                                v = int(float(v))
                            except Exception:
                                continue
                        cur[k] = v
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


def detect_text(client, path: Path, min_interval: float) -> tuple[str, int, float, str]:
    t0 = time.perf_counter()
    if not path.exists() or path.stat().st_size < 500:
        return "", 0, round(time.perf_counter() - t0, 3), "missing_jpg"
    try:
        data = prepare_bytes(path)
        last = None
        for attempt in range(6):
            acquire(min_interval)
            try:
                resp = client.detect_text(Image={"Bytes": data})
                break
            except ClientError as e:
                last = e
                code = e.response.get("Error", {}).get("Code", "")
                if code in ("ThrottlingException", "ProvisionedThroughputExceededException"):
                    time.sleep(min(20, 1.5 * (2**attempt)))
                    continue
                raise
        else:
            raise last  # type: ignore

        line_items = []
        for d in resp.get("TextDetections") or []:
            if d.get("Type") != "LINE":
                continue
            t = (d.get("DetectedText") or "").strip()
            if not t:
                continue
            geo = ((d.get("Geometry") or {}).get("BoundingBox") or {})
            top = float(geo.get("Top") or 0)
            left = float(geo.get("Left") or 0)
            line_items.append((top, left, t))
        line_items.sort(key=lambda x: (round(x[0] * 40) / 40, x[1]))
        lines = [t for _, _, t in line_items]
        text = "\n".join(lines)
        return text, len(lines), round(time.perf_counter() - t0, 3), ""
    except Exception as e:
        return "", 0, round(time.perf_counter() - t0, 3), f"{type(e).__name__}: {e}"[:240]


def score_text(text: str, title: str, orig: str) -> dict:
    o1 = title_overlap_score(text, title) if text and title else 0.0
    o2 = title_overlap_score(text, orig) if text and orig else 0.0
    f1 = title_fuzzy_score(text, title) if text and title else 0.0
    f2 = title_fuzzy_score(text, orig) if text and orig else 0.0
    return {
        "overlap_title": o1,
        "overlap_original": o2,
        "overlap_max": max(o1, o2),
        "fuzzy_title": f1,
        "fuzzy_original": f2,
        "fuzzy_max": max(f1, f2),
        "ocr_chars": len(text or ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids-file", default=str(CONSENSUS))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-interval", type=float, default=0.08)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--min-gain", type=float, default=0.25)
    ap.add_argument("--min-best", type=float, default=0.40)
    ap.add_argument("--min-fuzzy-best", type=float, default=0.55)
    ap.add_argument("--ge2-only", action="store_true", help="only movies with ≥2 local variants")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    meta = load_meta()
    ids = load_ids(Path(args.ids_file))
    jobs: list[tuple[int, str, str, Path]] = []  # id, source, stem_or_path, path
    for pid in ids:
        primary = POSTERS / f"{pid}.jpg"
        if primary.exists():
            jobs.append((pid, "primary", f"{pid}.jpg", primary))
        d = MULTI / str(pid)
        if not d.is_dir():
            continue
        variants = sorted(d.glob("*.jpg"))
        if args.ge2_only and len(variants) < 2:
            continue
        for vp in variants:
            jobs.append((pid, "variant", vp.stem, vp))

    if args.limit:
        # limit by movie id order
        keep = set(ids[: args.limit])
        jobs = [j for j in jobs if j[0] in keep]

    log(f"jobs={len(jobs)} movies={len({j[0] for j in jobs})} workers={args.workers}")

    client = boto3.client(
        "rekognition",
        region_name=args.region,
        config=Config(retries={"max_attempts": 8, "mode": "adaptive"}),
    )

    rows: list[dict] = []
    t0 = time.time()
    ok = err = 0

    def one(job: tuple[int, str, str, Path]) -> dict:
        pid, source, stem, path = job
        m = meta.get(pid, {})
        title = m.get("title") or ""
        orig = m.get("original_title") or ""
        text, n_lines, lat, error = detect_text(client, path, args.min_interval)
        sc = score_text(text, title, orig)
        return {
            "id": pid,
            "title": title,
            "original_title": orig,
            "year": m.get("year") or "",
            "source": source,
            "file_path": str(path.relative_to(DATA)) if path.is_relative_to(DATA) else str(path),
            "stem": stem,
            "n_lines": n_lines,
            "latency_s": lat,
            "error": error,
            "ocr_preview": (text or "").replace("\n", " | ")[:180],
            **sc,
        }

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(one, j): j for j in jobs}
        done = 0
        for fut in as_completed(futs):
            row = fut.result()
            rows.append(row)
            done += 1
            if row.get("error"):
                err += 1
            else:
                ok += 1
            if done % 25 == 0 or done == len(jobs):
                rate = done / max(1e-6, time.time() - t0)
                log(f"[{done}/{len(jobs)}] ok={ok} err={err} {rate:.2f}/s id={row['id']}")

    OUT_SCORES.parent.mkdir(parents=True, exist_ok=True)
    with OUT_SCORES.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SCORE_FIELDS)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (int(x["id"]), x["source"], x["stem"])):
            w.writerow(r)

    # propose swaps
    by_id: dict[int, list[dict]] = {}
    for r in rows:
        by_id.setdefault(int(r["id"]), []).append(r)

    swaps: list[dict] = []
    for pid, rs in sorted(by_id.items()):
        prim = [r for r in rs if r["source"] == "primary"]
        vars_ = [r for r in rs if r["source"] == "variant" and not r.get("error")]
        if not vars_:
            continue
        cur = prim[0] if prim else None
        cur_o = float(cur["overlap_max"]) if cur else 0.0
        cur_f = float(cur["fuzzy_max"]) if cur else 0.0
        best = max(vars_, key=lambda r: (float(r["overlap_max"]), float(r["fuzzy_max"]), int(r["ocr_chars"])))
        best_o = float(best["overlap_max"])
        best_f = float(best["fuzzy_max"])
        gain_o = best_o - cur_o
        gain_f = best_f - cur_f
        propose = 0
        reason = "no"
        if best_o >= args.min_best and gain_o >= args.min_gain:
            propose = 1
            reason = "overlap_gain"
        elif best_f >= args.min_fuzzy_best and gain_f >= args.min_gain and best_o >= 0.2:
            propose = 1
            reason = "fuzzy_gain"
        elif cur_o < 0.15 and best_o >= args.min_best:
            propose = 1
            reason = "current_near_zero"
        swaps.append(
            {
                "id": pid,
                "title": best.get("title") or "",
                "original_title": best.get("original_title") or "",
                "year": best.get("year") or "",
                "current_stem": (cur or {}).get("stem") or "",
                "current_overlap": cur_o,
                "current_fuzzy": cur_f,
                "best_stem": best["stem"],
                "best_file_path": best["file_path"],
                "best_overlap": best_o,
                "best_fuzzy": best_f,
                "gain_overlap": round(gain_o, 4),
                "gain_fuzzy": round(gain_f, 4),
                "n_variants": len(vars_),
                "propose": propose,
                "reason": reason,
            }
        )

    with OUT_SWAPS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SWAP_FIELDS)
        w.writeheader()
        for r in swaps:
            w.writerow(r)

    n_prop = sum(1 for r in swaps if int(r["propose"]) == 1)
    log(
        f"LISTO scores={OUT_SCORES} rows={len(rows)} "
        f"swaps_file={OUT_SWAPS} proposed={n_prop}/{len(swaps)} "
        f"elapsed={(time.time()-t0)/60:.1f}m"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
