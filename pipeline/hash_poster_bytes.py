#!/usr/bin/env python3
"""Freeze poster identity: TMDB file_path (locator hash) + SHA-256 of bytes.

Essay metrics are keyed by film `id`. That breaks if TMDB drops or rotates the
sheet. This sidecar never overwrites a measured file_path once hashed.

  python3 hash_poster_bytes.py              # freeze paths (measured + alts)
  python3 hash_poster_bytes.py --hash-local # SHA-256 of posters/ and posters_multi/
  python3 hash_poster_bytes.py --s3         # SHA-256 of workshop posters/{id}.jpg
  python3 hash_poster_bytes.py --fetch      # download missing alts from TMDB w500

Writes pipeline/data/poster_bytes.csv
Join: essay → role=measured; alts → (id, file_path).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "poster_bytes.csv"
POSTERS = DATA / "posters"
MULTI = DATA / "posters_multi"
ALTS_JSON = HERE.parent / "site" / "data" / "poster_alts.json"
EXPLORER = HERE.parent / "site" / "data" / "explorer.js"
SRC_CSV = DATA / "poster_src.csv"
BACKFILL = DATA / "poster_paths_backfill.csv"
HORROR = DATA / "horror_movies.csv"

FIELDS = (
    "id",
    "file_path",
    "tmdb_hash",
    "role",
    "size",
    "sha256",
    "md5",
    "bytes",
    "source",
    "status",
    "hashed_at",
)

TMDB_W500 = "https://image.tmdb.org/t/p/w500"
S3_BUCKET = os.environ.get("S3_BUCKET", "")  # bucket holding the posters; required for the s3 pass
S3_KEY = "posters/{id}.jpg"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tmdb_hash(file_path: str) -> str:
    name = Path(str(file_path or "").lstrip("/")).name
    return name[:-4] if name.lower().endswith(".jpg") else name


def norm_path(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("/") and raw.lower().endswith(".jpg"):
        return raw
    name = Path(raw).name
    return f"/{name}" if name.lower().endswith(".jpg") else ""


def hash_bytes(data: bytes) -> tuple[str, str]:
    return hashlib.sha256(data).hexdigest(), hashlib.md5(data).hexdigest()


def hash_file(path: Path) -> tuple[str, str, int] | None:
    if not path.is_file() or path.stat().st_size < 500:
        return None
    data = path.read_bytes()
    sha, md5 = hash_bytes(data)
    return sha, md5, len(data)


def load_src() -> dict[int, str]:
    out: dict[int, str] = {}
    if not SRC_CSV.is_file():
        return out
    with SRC_CSV.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                out[int(r["id"])] = (r.get("poster_src") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue
    return out


def load_explorer_paths() -> dict[int, str]:
    out: dict[int, str] = {}
    if not EXPLORER.is_file():
        return out
    text = EXPLORER.read_text(encoding="utf-8")
    start = text.find("const POSTERS=")
    if start < 0:
        start = text.find("POSTERS=")
        if start < 0:
            return out
        start += len("POSTERS=")
    else:
        start += len("const POSTERS=")
    end = text.rfind(";")
    rows = json.loads(text[start:end])
    for row in rows:
        try:
            pid = int(row[7])
            path = norm_path(str(row[2] or ""))
        except (IndexError, TypeError, ValueError):
            continue
        if path:
            out[pid] = path
    return out


def load_catalog_paths() -> dict[int, str]:
    out: dict[int, str] = {}
    for src in (HORROR, BACKFILL):
        if not src.is_file():
            continue
        with src.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                path = norm_path(r.get("poster_path") or "")
                if path:
                    out[pid] = path
    return out


def load_alts() -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    if not ALTS_JSON.is_file():
        return rows
    data = json.loads(ALTS_JSON.read_text(encoding="utf-8"))
    for pid, items in data.items():
        try:
            n = int(pid)
        except (TypeError, ValueError):
            continue
        for item in items or []:
            path = norm_path(item[0] if item else "")
            if path:
                rows.append((n, path))
    return rows


def load_existing() -> dict[tuple[int, str], dict]:
    out: dict[tuple[int, str], dict] = {}
    if not OUT.is_file():
        return out
    with OUT.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            path = norm_path(r.get("file_path") or "")
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            out[(pid, path)] = r
    return out


def blank_row(pid: int, path: str, role: str, source: str) -> dict:
    return {
        "id": pid,
        "file_path": path,
        "tmdb_hash": tmdb_hash(path),
        "role": role,
        "size": "",
        "sha256": "",
        "md5": "",
        "bytes": "",
        "source": source,
        "status": "path_only",
        "hashed_at": "",
    }


def source_for(pid: int, src_map: dict[int, str]) -> str:
    s = src_map.get(pid) or "tmdb"
    if s == "no_poster":
        return "none"
    return s


def apply_hash(row: dict, hashed: tuple[str, str, int], size: str) -> None:
    sha, md5, n = hashed
    row["sha256"] = sha
    row["md5"] = md5
    row["bytes"] = n
    row["size"] = size
    row["status"] = "hashed"
    row["hashed_at"] = now_iso()


def write_rows(rows: dict[tuple[int, str], dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for key in sorted(rows, key=lambda x: (x[0], x[1])):
            w.writerow(rows[key])


def freeze_paths(keep: frozenset[int]) -> dict[tuple[int, str], dict]:
    rows = load_existing()
    src_map = load_src()
    measured = load_explorer_paths()
    catalog = load_catalog_paths()
    for pid, path in catalog.items():
        measured.setdefault(pid, path)

    n_meas = n_alt = 0
    for pid, path in measured.items():
        if pid not in keep:
            continue
        key = (pid, path)
        if key not in rows:
            rows[key] = blank_row(pid, path, "measured", source_for(pid, src_map))
            n_meas += 1
        elif rows[key].get("role") != "measured":
            # Frozen measured path wins over an alt row of the same file.
            rows[key]["role"] = "measured"

    for pid, path in load_alts():
        if pid not in keep:
            continue
        key = (pid, path)
        if key in rows:
            continue
        rows[key] = blank_row(pid, path, "alt", "tmdb")
        n_alt += 1

    have_meas = {pid for (pid, _), r in rows.items() if r.get("role") == "measured"}
    n_omdb = 0
    for pid in keep:
        if pid in have_meas:
            continue
        src = source_for(pid, src_map)
        if src == "none":
            continue
        row = blank_row(pid, "", "measured", src)
        if src == "omdb":
            row["status"] = "omdb_no_tmdb_path"
        rows[(pid, "")] = row
        n_omdb += 1
        n_meas += 1
    print(
        f"freeze new measured={n_meas:,} (omdb_no_path={n_omdb:,}) "
        f"new alts={n_alt:,} total={len(rows):,}"
    )
    return rows


def hash_local(rows: dict[tuple[int, str], dict], force: bool) -> int:
    n = 0
    for (pid, path), row in rows.items():
        if row.get("sha256") and not force:
            continue
        candidates = []
        if row.get("role") == "measured":
            candidates.append(POSTERS / f"{pid}.jpg")
        candidates.append(MULTI / str(pid) / Path(path).name)
        local = next((p for p in candidates if p.is_file() and p.stat().st_size > 500), None)
        got = hash_file(local) if local else None
        if not got:
            continue
        apply_hash(row, got, row.get("size") or "local")
        n += 1
    print(f"hash-local n={n:,}")
    return n


def hash_s3(
    rows: dict[tuple[int, str], dict],
    force: bool,
    profile: str,
    limit: int = 0,
    workers: int = 16,
) -> int:
    import boto3

    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    s3 = session.client("s3")
    lock = threading.Lock()
    measured = [
        (k, r)
        for k, r in rows.items()
        if r.get("role") == "measured" and r.get("file_path") and (force or not r.get("sha256"))
    ]
    if limit:
        measured = measured[:limit]
    if not S3_BUCKET:
        raise SystemExit("set S3_BUCKET to run the s3 pass")
    print(f"s3 todo measured={len(measured):,} bucket={S3_BUCKET} workers={workers}", flush=True)

    def one(pid: int) -> tuple[int, tuple[str, str, int] | None, str]:
        key = S3_KEY.format(id=pid)
        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
            data = obj["Body"].read()
            if len(data) < 500:
                return pid, None, "s3_too_small"
            return pid, (*hash_bytes(data), len(data)), "hashed"
        except Exception as e:
            return pid, None, f"s3_error:{type(e).__name__}"[:80]

    ok = err = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(one, k[0]): k for k, _r in measured}
        for n, fut in enumerate(as_completed(futs), 1):
            key = futs[fut]
            pid, hashed, status = fut.result()
            row = rows[key]
            with lock:
                if hashed:
                    apply_hash(row, hashed, "s3")
                    ok += 1
                else:
                    row["status"] = status
                    err += 1
            if n % 500 == 0 or n == len(measured):
                write_rows(rows)
                print(f"  s3 [{n}/{len(measured)}] ok={ok} err={err}", flush=True)
    print(f"hash-s3 ok={ok:,} err={err:,}")
    return ok


def fetch_tmdb(rows: dict[tuple[int, str], dict], force: bool, limit: int) -> int:
    import requests

    todo = [(k, r) for k, r in rows.items() if force or not r.get("sha256")]
    if limit:
        todo = todo[:limit]
    print(f"fetch todo={len(todo):,}", flush=True)
    sess = requests.Session()
    ok = err = n = 0
    for (_pid, path), row in todo:
        url = TMDB_W500 + path
        try:
            r = sess.get(url, timeout=60)
            if r.status_code == 404:
                row["status"] = "missing_404"
                err += 1
                n += 1
                continue
            r.raise_for_status()
            data = r.content
            if len(data) < 500:
                row["status"] = "fetch_too_small"
                err += 1
                n += 1
                continue
            apply_hash(row, (*hash_bytes(data), len(data)), "w500")
            dest = MULTI / str(_pid) / Path(path).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_file():
                dest.write_bytes(data)
            ok += 1
        except Exception as e:
            row["status"] = f"fetch_error:{type(e).__name__}"[:80]
            err += 1
        n += 1
        if n % 200 == 0:
            write_rows(rows)
            print(f"  fetch [{n}/{len(todo)}] ok={ok} err={err}", flush=True)
    print(f"fetch ok={ok:,} err={err:,}")
    return ok


def main() -> int:
    from corpus import canonical_ids

    ap = argparse.ArgumentParser()
    ap.add_argument("--hash-local", action="store_true")
    ap.add_argument("--s3", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--profile", default="sandbox_bedrock")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    keep = canonical_ids()
    rows = freeze_paths(keep)
    write_rows(rows)
    if args.hash_local:
        hash_local(rows, args.force)
        write_rows(rows)
    if args.s3:
        hash_s3(rows, args.force, args.profile, args.limit, args.workers)
        write_rows(rows)
    if args.fetch:
        fetch_tmdb(rows, args.force, args.limit)
        write_rows(rows)

    hashed = sum(1 for r in rows.values() if r.get("sha256"))
    meas = sum(1 for r in rows.values() if r.get("role") == "measured")
    alts = sum(1 for r in rows.values() if r.get("role") == "alt")
    missing = sum(1 for r in rows.values() if r.get("status") == "missing_404")
    print(
        f"LISTO {OUT} rows={len(rows):,} measured={meas:,} alts={alts:,} "
        f"sha256={hashed:,} missing_404={missing:,}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
