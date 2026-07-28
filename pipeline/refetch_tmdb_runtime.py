#!/usr/bin/env python3
"""Refetch TMDB /movie/{id} runtime for corpus posters without IMDb id
and with missing/zero runtime in horror_movies.csv.

Writes:
  data/tmdb_runtime_refetch_3151.csv  (sidecar report)
  data/horror_movies.csv              (runtime updates; new rows if absent)

Usage:
  TMDB_API_KEY=... python3 refetch_tmdb_runtime.py
  python3 refetch_tmdb_runtime.py --workers 8
"""
from __future__ import annotations

import argparse
import csv
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
HM = DATA / "horror_movies.csv"
SIDECAR = DATA / "imdb_ids.csv"
POSTERS = DATA / "posters.csv"
REPORT = DATA / "tmdb_runtime_refetch_3151.csv"

MOVIE_URL = "https://api.themoviedb.org/3/movie/{pid}"


def auth_kwargs(api_key: str) -> dict:
    key = (api_key or "").strip()
    if key.startswith("eyJ"):
        return {"headers": {"Authorization": f"Bearer {key}"}}
    return {"params": {"api_key": key}}


def parse_runtime(raw) -> float:
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return 0.0
    try:
        v = float(s)
        return 0.0 if v != v or v < 0 else v
    except ValueError:
        return -1.0  # text / non-numeric


def load_has_tt() -> set[int]:
    out: set[int] = set()
    if not SIDECAR.exists():
        return out
    with SIDECAR.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, ValueError, TypeError):
                continue
            if (r.get("imdb_id") or "").strip().startswith("tt"):
                out.add(pid)
    return out


def load_poster_ids() -> dict[int, str]:
    out: dict[int, str] = {}
    with POSTERS.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, ValueError, TypeError):
                continue
            if pid not in out:
                out[pid] = (r.get("title") or "").strip()
    return out


def load_hm_runtime_title() -> dict[int, tuple[float, str]]:
    """id -> (runtime_num, title). runtime_num < 0 means text."""
    out: dict[int, tuple[float, str]] = {}
    if not HM.exists():
        return out
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, ValueError, TypeError):
                continue
            title = (r.get("title") or r.get("original_title") or "").strip()
            out[pid] = (parse_runtime(r.get("runtime")), title)
    return out


def target_ids(
    posters: dict[int, str],
    has_tt: set[int],
    hm: dict[int, tuple[float, str]],
) -> list[tuple[int, str, float]]:
    """Return (id, title, runtime_before) for no-tt + unknown runtime.

    Unknown = missing from HM or runtime 0/nan. Text runtimes (rt < 0) are
    left alone (already classifiable as short).
    """
    todo: list[tuple[int, str, float]] = []
    for pid, poster_title in posters.items():
        if pid in has_tt:
            continue
        if pid not in hm:
            todo.append((pid, poster_title, 0.0))
            continue
        rt, title = hm[pid]
        if rt == 0.0:
            todo.append((pid, title or poster_title, 0.0))
    return sorted(todo, key=lambda x: x[0])


def fetch_runtime(
    session: requests.Session, api_key: str, pid: int
) -> tuple[str, float | None, str]:
    """Return (status, runtime_or_None, title).

    status: ok | still_zero | not_found | error
    """
    url = MOVIE_URL.format(pid=pid)
    kwargs = auth_kwargs(api_key)
    for attempt in range(6):
        try:
            r = session.get(url, timeout=30, **kwargs)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code == 404:
            return "not_found", None, ""
        if r.status_code == 401:
            raise SystemExit(
                "TMDB 401 Unauthorized — check TMDB_API_KEY "
                "(v3 api_key or v4 Bearer token)."
            )
        if not r.ok:
            time.sleep(1 + attempt)
            continue
        m = r.json()
        title = (m.get("title") or m.get("original_title") or "").strip()
        raw = m.get("runtime")
        try:
            rt = float(raw) if raw is not None else 0.0
            if rt != rt or rt < 0:
                rt = 0.0
        except (TypeError, ValueError):
            rt = 0.0
        if rt > 0:
            return "ok", rt, title
        return "still_zero", 0.0, title
    return "error", None, ""


def merge_runtimes(updates: dict[int, float], titles: dict[int, str]) -> tuple[int, int]:
    """Update runtime on existing HM rows; append minimal rows for new ids.

    Returns (updated_existing, appended_new).
    """
    if not updates:
        return 0, 0
    if not HM.exists():
        raise SystemExit(f"missing {HM}")

    with HM.open(encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        if "id" not in fields or "runtime" not in fields:
            raise SystemExit(f"{HM} needs id and runtime columns")
        rows = list(reader)

    seen: set[int] = set()
    updated = 0
    for row in rows:
        try:
            pid = int(row["id"])
        except (KeyError, ValueError, TypeError):
            continue
        seen.add(pid)
        if pid not in updates:
            continue
        new_rt = updates[pid]
        old = parse_runtime(row.get("runtime"))
        if old > 0:
            continue  # never overwrite a known positive runtime
        if new_rt > 0:
            row["runtime"] = str(int(new_rt) if new_rt == int(new_rt) else new_rt)
            updated += 1

    appended = 0
    for pid, new_rt in sorted(updates.items()):
        if pid in seen or new_rt <= 0:
            continue
        row = {k: "" for k in fields}
        row["id"] = str(pid)
        row["runtime"] = str(int(new_rt) if new_rt == int(new_rt) else new_rt)
        if "title" in fields:
            row["title"] = titles.get(pid, "")
        if "original_title" in fields and not row.get("original_title"):
            row["original_title"] = titles.get(pid, "")
        rows.append(row)
        appended += 1

    tmp = HM.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(HM)
    return updated, appended


def write_report(rows: list[dict]) -> None:
    fields = ["id", "title", "runtime_before", "runtime_after", "status"]
    with REPORT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sorted(rows, key=lambda x: int(x["id"])):
            w.writerow({k: r.get(k, "") for k in fields})


def classify_no_tt(
    posters: dict[int, str],
    has_tt: set[int],
    hm: dict[int, tuple[float, str]],
) -> dict[str, int]:
    short = feature = unknown = 0
    for pid in posters:
        if pid in has_tt:
            continue
        if pid not in hm:
            unknown += 1
            continue
        rt, _ = hm[pid]
        if rt < 0:
            short += 1  # text runtime → short bucket per user
        elif rt <= 0:
            unknown += 1
        elif rt <= 40:
            short += 1
        else:
            feature += 1
    return {
        "no_tt": len(posters) - sum(1 for p in posters if p in has_tt),
        "short": short,
        "feature": feature,
        "unknown": unknown,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--delay", type=float, default=0.04)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--report-only",
        action="store_true",
        help="skip API; reclassify from current HM + write nothing",
    )
    args = ap.parse_args()

    posters = load_poster_ids()
    has_tt = load_has_tt()
    hm = load_hm_runtime_title()

    if args.report_only:
        c = classify_no_tt(posters, has_tt, hm)
        print(
            f"no_tt={c['no_tt']} short={c['short']} "
            f"feature={c['feature']} unknown={c['unknown']}"
        )
        return

    if not args.api_key:
        raise SystemExit(
            "Need TMDB_API_KEY or --api-key\n"
            "Get one free at https://www.themoviedb.org/settings/api"
        )

    todo = target_ids(posters, has_tt, hm)
    if args.limit:
        todo = todo[: args.limit]
    print(f"target unknown-runtime (no IMDb): {len(todo):,}")
    if not todo:
        c = classify_no_tt(posters, has_tt, hm)
        print(
            f"nothing to fetch. no_tt={c['no_tt']} short={c['short']} "
            f"feature={c['feature']} unknown={c['unknown']}"
        )
        return

    workers = max(1, args.workers)
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=workers, pool_maxsize=workers
    )
    session.mount("https://", adapter)

    report: list[dict] = []
    updates: dict[int, float] = {}
    titles: dict[int, str] = {}
    lock = threading.Lock()
    t0 = time.time()
    done = 0
    ok_n = still_n = nf_n = err_n = 0

    def work(item: tuple[int, str, float]) -> dict:
        pid, title_before, rt_before = item
        status, rt, title_api = fetch_runtime(session, args.api_key, pid)
        if args.delay:
            time.sleep(args.delay)
        title = title_api or title_before
        after = rt if rt is not None else rt_before
        if status == "ok" and rt is not None:
            after = rt
        elif status == "still_zero":
            after = 0.0
        else:
            after = rt_before
        return {
            "id": pid,
            "title": title,
            "runtime_before": rt_before,
            "runtime_after": after if status in {"ok", "still_zero"} else "",
            "status": status,
            "_rt": rt,
        }

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, item) for item in todo]
        for fut in as_completed(futs):
            row = fut.result()
            with lock:
                done += 1
                st = row["status"]
                if st == "ok":
                    ok_n += 1
                    updates[int(row["id"])] = float(row["_rt"])
                    titles[int(row["id"])] = row["title"]
                elif st == "still_zero":
                    still_n += 1
                elif st == "not_found":
                    nf_n += 1
                else:
                    err_n += 1
                report.append({
                    "id": row["id"],
                    "title": row["title"],
                    "runtime_before": row["runtime_before"],
                    "runtime_after": row["runtime_after"],
                    "status": row["status"],
                })
                if done % 200 == 0 or done == len(todo):
                    rate = done / max(time.time() - t0, 1e-6)
                    print(
                        f"{done}/{len(todo)} ok={ok_n} still0={still_n} "
                        f"404={nf_n} err={err_n} {rate:.1f}/s",
                        flush=True,
                    )
                    write_report(report)

    write_report(report)
    updated, appended = merge_runtimes(updates, titles)
    print(
        f"horror_movies.csv: updated_runtime={updated} appended_new={appended}"
    )
    print(f"report → {REPORT} ({len(report)} rows)")

    hm2 = load_hm_runtime_title()
    c = classify_no_tt(posters, has_tt, hm2)
    print(
        f"reclassify no_tt={c['no_tt']}: "
        f"short={c['short']} feature={c['feature']} unknown={c['unknown']}"
    )


if __name__ == "__main__":
    main()
