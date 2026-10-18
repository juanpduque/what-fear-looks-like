#!/usr/bin/env python3
"""Descarga posters de S3 por id conocido (sin `aws s3 sync`).

`aws s3 sync` sobre un prefijo con 68k+ objetos se colgo dos veces seguidas en
EC2 (confirmado via CloudWatch NetworkIn ~0 durante >50min) sin ningun error
visible. En vez de depender de su listado/diff interno, bajamos cada archivo
por su ruta exacta (conocida via ids-file) en paralelo con boto3 — mismo patron
que ya funciono para la subida equivalente.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3

HERE = Path(__file__).parent
POSTERS = HERE / "data" / "posters"


def download_one(s3, bucket, keys, pid, dest: Path):
    local = dest / f"{pid}.jpg"
    if local.exists() and local.stat().st_size > 2000:
        return "skip"
    last_err = None
    for key in keys:
        try:
            s3.download_file(bucket, key, str(local))
            return "ok"
        except Exception as e:
            last_err = e
            local.unlink(missing_ok=True)
    return f"err:{last_err}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", default="", help="tried as {prefix}/posters/{id}.jpg")
    ap.add_argument("--prefix2", default="", help="fallback prefix if not found under --prefix")
    ap.add_argument("--key-prefix", default="", help="if set, also try {key-prefix}/{id}.jpg")
    ap.add_argument("--dest", default=str(POSTERS))
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument(
        "--progress-file",
        default="",
        help="periodic JSON progress (so a long silent phase is still visible)",
    )
    args = ap.parse_args()
    prefixes = [p for p in (args.prefix, args.prefix2) if p]
    if not prefixes and not args.key_prefix:
        raise SystemExit("need --prefix and/or --key-prefix")

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip()]
    print(f"ids={len(ids):,} workers={args.workers}", flush=True)

    prog_path = Path(args.progress_file) if args.progress_file else None

    def write_progress(i, ok, skip, err):
        if not prog_path:
            return
        prog_path.parent.mkdir(parents=True, exist_ok=True)
        prog_path.write_text(
            json.dumps(
                {
                    "phase": "download_posters",
                    "done": i,
                    "target": len(ids),
                    "ok": ok,
                    "skip": skip,
                    "err": err,
                    "ts": time.time(),
                }
            )
        )

    s3 = boto3.client("s3")
    ok = skip = err = 0
    write_progress(0, 0, 0, 0)

    def keys_for(pid):
        out = []
        if args.key_prefix:
            out.append(f"{args.key_prefix.rstrip('/')}/{pid}.jpg")
        for prefix in prefixes:
            out.append(f"{prefix}/posters/{pid}.jpg")
        return out

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(download_one, s3, args.bucket, keys_for(pid), pid, dest): pid for pid in ids
        }
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            if r == "ok":
                ok += 1
            elif r == "skip":
                skip += 1
            else:
                err += 1
                if err <= 5:
                    print(r, file=sys.stderr)
            if i % 2000 == 0:
                print(f"  {i:,}/{len(ids):,} ok={ok} skip={skip} err={err}", flush=True)
                write_progress(i, ok, skip, err)
    write_progress(len(ids), ok, skip, err)
    print(f"LISTO ok={ok} skip={skip} err={err}")
    if ok + skip < len(ids) * 0.5:
        sys.exit(1)


if __name__ == "__main__":
    main()
