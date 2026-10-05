#!/usr/bin/env python3
"""Upload poster JPGs to workshop S3 by id list (parallel).

Usage:
  AWS_PROFILE=sandbox_bedrock AWS_DEFAULT_REGION=us-east-1 \\
    python3 pipeline/aws/upload_posters_workshop.py gap

  python3 pipeline/aws/upload_posters_workshop.py all --workers 16
  python3 pipeline/aws/upload_posters_workshop.py gap --sample 50
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / "pipeline" / "data" / "qa"
DEFAULT_SRC = Path("/Volumes/Adata Bituan/what-fear-looks-like-data/posters")
BUCKET = os.environ.get("S3_BUCKET", "wflike-workshop-posters-633183588025")
PREFIX = os.environ.get("S3_PREFIX", "posters")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def load_ids(mode: str) -> list[int]:
    if mode == "gap":
        path = QA / "gap_yunet0_rek_faces_ids.txt"
    elif mode == "all":
        path = QA / "master_poster_ids.txt"
    else:
        path = Path(mode)
    return [int(x) for x in path.read_text().split() if x.strip().isdigit()]


def upload_one(s3, src: Path, key: str) -> tuple[str, str]:
    try:
        s3.upload_file(str(src), BUCKET, key)
        return ("ok", key)
    except ClientError as e:
        return ("err", f"{key}: {e}")
    except Exception as e:
        return ("err", f"{key}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="gap", help="gap | all | path/to/ids.txt")
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-existing", action="store_true", help="HEAD object first (slower)")
    args = ap.parse_args()

    src_dir = Path(args.src)
    if not src_dir.is_dir():
        raise SystemExit(f"posters dir missing: {src_dir}")

    ids = load_ids(args.mode)
    if args.sample:
        ids = ids[: args.sample]

    print(f"profile={os.environ.get('AWS_PROFILE')} bucket=s3://{BUCKET}/{PREFIX}/")
    print(f"src={src_dir} ids={len(ids)} workers={args.workers}")
    s3 = boto3.client("s3", region_name=REGION)
    sts = boto3.client("sts", region_name=REGION)
    print("identity", {k: sts.get_caller_identity()[k] for k in ("UserId", "Account", "Arn")})

    if args.dry_run:
        print("dry-run first ids", ids[:10])
        return

    # Stream: check local + upload in workers (no full pre-scan on slow USB).
    def work(pid: int) -> tuple[str, str]:
        f = src_dir / f"{pid}.jpg"
        if not f.is_file():
            return ("miss", str(pid))
        key = f"{PREFIX}/{pid}.jpg"
        if args.skip_existing:
            try:
                s3.head_object(Bucket=BUCKET, Key=key)
                return ("skip", key)
            except ClientError:
                pass
        return upload_one(s3, f, key)

    t0 = time.time()
    ok = err = miss = skip = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, pid): pid for pid in ids}
        for n, fut in enumerate(as_completed(futs), 1):
            status, msg = fut.result()
            if status == "ok":
                ok += 1
            elif status == "miss":
                miss += 1
            elif status == "skip":
                skip += 1
            else:
                err += 1
                if err <= 20:
                    print("ERR", msg, flush=True)
            if n % 100 == 0 or n == len(futs):
                rate = n / max(1e-6, time.time() - t0)
                print(
                    f"[{n}/{len(futs)}] ok={ok} skip={skip} miss={miss} err={err} "
                    f"{rate:.1f}/s eta={(len(futs)-n)/max(rate,1e-6)/60:.1f}m",
                    flush=True,
                )
    print(f"DONE ok={ok} skip={skip} miss={miss} err={err}")


if __name__ == "__main__":
    main()
