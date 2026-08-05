#!/usr/bin/env python3
"""Batch DetectCustomLabels for wflike-medium-clf over S3 posters.

Reads an ids file (one id per line) and calls Rekognition Custom Labels against
s3://BUCKET/POSTER_PREFIX/{id}.jpg. Resumes from OUT CSV. Writes periodic
progress JSON + partial CSV to local OUT and optionally syncs via external chain.

  export AWS_PROFILE=sandbox AWS_EC2_METADATA_DISABLED=true
  python3 aws_custom_labels_infer.py \\
    --ids-file data/qa/medium_custom_labels/infer_ids.txt \\
    --out data/qa/medium_custom_labels/infer_full.csv \\
    --workers 8 --min-interval 0.05

Requires project version RUNNING (StartProjectVersion). Cost: inference-unit
hours while RUNNING + per-image DetectCustomLabels.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "us-east-1"
VERSION_ARN_DEFAULT = (
    "arn:aws:rekognition:us-east-1:567596065542:project/"
    "wflike-medium-clf/version/v202608040132/1785807179332"
)
BUCKET_DEFAULT = "sagemaker-studio-a5572760"
POSTER_PREFIX_DEFAULT = "wflike-community-72k/posters"
CLASSES = ("painted", "photo", "composite")

FIELDS = [
    "id",
    "pred",
    "confidence",
    "painted",
    "photo",
    "composite",
    "n_labels",
    "status",
    "error",
    "ts",
]

_print_lock = threading.Lock()
_write_lock = threading.Lock()
_rate_lock = threading.Lock()
_next_slot = 0.0
_stats = {"ok": 0, "err": 0, "skip": 0, "done": 0}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def acquire(min_interval: float) -> None:
    global _next_slot
    if min_interval <= 0:
        return
    with _rate_lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + min_interval
        wait = slot - now
    if wait > 0:
        time.sleep(wait)


def load_done(path: Path) -> set[int]:
    done: set[int] = set()
    if not path.exists():
        return done
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                if (r.get("status") or "").strip() == "ok":
                    done.add(int(r["id"]))
            except Exception:
                pass
    return done


def load_ids(path: Path) -> list[int]:
    ids: list[int] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "," in s and s.split(",", 1)[0].isdigit():
                s = s.split(",", 1)[0]
            try:
                ids.append(int(s))
            except ValueError:
                continue
    return ids


def scores_from_labels(labels: list[dict]) -> dict[str, float]:
    out = {c: 0.0 for c in CLASSES}
    for lab in labels or []:
        name = (lab.get("Name") or "").strip().lower()
        conf = float(lab.get("Confidence") or 0.0) / 100.0
        if name in out:
            out[name] = max(out[name], conf)
    return out


def predict_one(client, version_arn: str, bucket: str, key: str, min_conf: float) -> dict:
    resp = client.detect_custom_labels(
        ProjectVersionArn=version_arn,
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        MinConfidence=min_conf,
    )
    labels = resp.get("CustomLabels") or []
    scores = scores_from_labels(labels)
    if scores and any(scores.values()):
        pred = max(scores, key=scores.get)
        conf = scores[pred]
    elif labels:
        pred = (labels[0].get("Name") or "").strip().lower()
        conf = float(labels[0].get("Confidence") or 0.0) / 100.0
        scores = scores_from_labels(labels)
    else:
        pred = ""
        conf = 0.0
    return {
        "pred": pred,
        "confidence": round(conf, 6),
        "painted": round(scores.get("painted", 0.0), 6),
        "photo": round(scores.get("photo", 0.0), 6),
        "composite": round(scores.get("composite", 0.0), 6),
        "n_labels": len(labels),
        "status": "ok",
        "error": "",
    }


def write_progress(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", REGION))
    ap.add_argument("--version-arn", default=os.environ.get("VERSION_ARN", VERSION_ARN_DEFAULT))
    ap.add_argument("--bucket", default=os.environ.get("POSTER_BUCKET", BUCKET_DEFAULT))
    ap.add_argument(
        "--poster-prefix",
        default=os.environ.get("POSTER_PREFIX", POSTER_PREFIX_DEFAULT),
        help="S3 key prefix without trailing slash (…/posters)",
    )
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", required=True, help="CSV path (resume-safe)")
    ap.add_argument("--progress", default="", help="progress JSON path")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("WORKERS", "8")))
    ap.add_argument(
        "--min-interval",
        type=float,
        default=float(os.environ.get("MIN_INTERVAL", "0.05")),
    )
    ap.add_argument("--min-confidence", type=float, default=0.0)
    ap.add_argument("--limit", type=int, default=int(os.environ.get("LIMIT", "0")))
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument(
        "--wait-running",
        action="store_true",
        help="poll DescribeProjectVersions until RUNNING before infer",
    )
    ap.add_argument("--wait-seconds", type=int, default=30)
    ap.add_argument("--wait-timeout", type=int, default=3600)
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    progress_path = Path(args.progress) if args.progress else out.with_suffix(".progress.json")

    ids = load_ids(Path(args.ids_file))
    if args.limit and args.limit > 0:
        ids = ids[: args.limit]
    done = load_done(out)
    todo = [i for i in ids if i not in done]
    log(
        f"ids={len(ids)} done={len(done)} todo={len(todo)} "
        f"workers={args.workers} interval={args.min_interval} "
        f"s3://{args.bucket}/{args.poster_prefix}/ version={args.version_arn.split('/')[-2]}"
    )

    cfg = Config(retries={"max_attempts": 10, "mode": "adaptive"}, max_pool_connections=max(16, args.workers * 2))
    client = boto3.client("rekognition", region_name=args.region, config=cfg)

    if args.wait_running:
        project_arn = os.environ.get(
            "PROJECT_ARN",
            "arn:aws:rekognition:us-east-1:567596065542:project/wflike-medium-clf/1785807168455",
        )
        version_name = args.version_arn.split("/version/")[1].split("/")[0]
        min_iu = int(os.environ.get("MIN_IU", "1"))
        started = False
        t0 = time.time()
        while True:
            desc = client.describe_project_versions(
                ProjectArn=project_arn, VersionNames=[version_name]
            )
            vers = (desc.get("ProjectVersionDescriptions") or [None])[0]
            st = (vers or {}).get("Status")
            log(f"model_status={st} msg={(vers or {}).get('StatusMessage', '')[:100]}")
            if st == "RUNNING":
                break
            if st in ("FAILED", "TRAINING_FAILED"):
                raise SystemExit(f"model not startable: {st}")
            # Belt-and-suspenders: chain should StartProjectVersion first; if still
            # STOPPED (race / missed start), start once here — never leave waiting forever.
            if st in ("STOPPED", "TRAINING_COMPLETED") and not started:
                log(f"StartProjectVersion MinInferenceUnits={min_iu} (was {st})")
                client.start_project_version(
                    ProjectVersionArn=args.version_arn,
                    MinInferenceUnits=min_iu,
                )
                started = True
            if time.time() - t0 > args.wait_timeout:
                raise SystemExit(f"timeout waiting RUNNING (last={st})")
            time.sleep(args.wait_seconds)

    new_file = not out.exists()
    f_out = out.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_out, fieldnames=FIELDS)
    if new_file:
        writer.writeheader()
        f_out.flush()

    t_start = time.time()
    buf: list[dict] = []

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        with _write_lock:
            for row in buf:
                writer.writerow(row)
            f_out.flush()
            buf = []
            elapsed = max(1e-6, time.time() - t_start)
            rate = _stats["done"] / elapsed
            remaining = len(todo) - _stats["done"]
            eta_s = remaining / rate if rate > 0 else None
            write_progress(
                progress_path,
                {
                    "ts": utc_now(),
                    "todo": len(todo),
                    "done": _stats["done"],
                    "ok": _stats["ok"],
                    "err": _stats["err"],
                    "rate_per_sec": round(rate, 3),
                    "eta_seconds": None if eta_s is None else int(eta_s),
                    "out": str(out),
                    "version_arn": args.version_arn,
                },
            )

    def work(pid: int) -> dict:
        key = f"{args.poster_prefix.rstrip('/')}/{pid}.jpg"
        acquire(args.min_interval)
        try:
            row = predict_one(client, args.version_arn, args.bucket, key, args.min_confidence)
            row.update({"id": pid, "ts": utc_now()})
            return row
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            msg = e.response.get("Error", {}).get("Message", str(e))[:240]
            # NotFound / InvalidS3Object → soft miss
            status = "miss" if code in ("InvalidS3ObjectException", "ResourceNotFoundException") else "error"
            return {
                "id": pid,
                "pred": "",
                "confidence": "",
                "painted": "",
                "photo": "",
                "composite": "",
                "n_labels": 0,
                "status": status,
                "error": f"{code}:{msg}",
                "ts": utc_now(),
            }
        except Exception as e:
            return {
                "id": pid,
                "pred": "",
                "confidence": "",
                "painted": "",
                "photo": "",
                "composite": "",
                "n_labels": 0,
                "status": "error",
                "error": str(e)[:240],
                "ts": utc_now(),
            }

    if not todo:
        log("nothing to do")
        write_progress(
            progress_path,
            {
                "ts": utc_now(),
                "todo": 0,
                "done": 0,
                "ok": 0,
                "err": 0,
                "note": "already complete",
                "out": str(out),
            },
        )
        f_out.close()
        return 0

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(work, pid): pid for pid in todo}
        for fut in as_completed(futs):
            row = fut.result()
            st = row.get("status")
            with _write_lock:
                if st == "ok":
                    _stats["ok"] += 1
                else:
                    _stats["err"] += 1
                _stats["done"] += 1
                buf.append(row)
                n = _stats["done"]
            if n % 25 == 0 or n == len(todo):
                log(
                    f"[{n}/{len(todo)}] ok={_stats['ok']} err={_stats['err']} "
                    f"last_id={row.get('id')} pred={row.get('pred')} st={st}"
                )
            if len(buf) >= args.save_every or n == len(todo):
                flush()

    flush()
    f_out.close()
    log(f"DONE ok={_stats['ok']} err={_stats['err']} out={out}")
    write_progress(
        progress_path,
        {
            "ts": utc_now(),
            "todo": len(todo),
            "done": _stats["done"],
            "ok": _stats["ok"],
            "err": _stats["err"],
            "finished": True,
            "out": str(out),
            "version_arn": args.version_arn,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
