#!/usr/bin/env python3
"""Fill missing/zero runtimes from IMDb title.basics runtimeMinutes.

Target: posters.csv ids with a valid tt… in imdb_ids.csv and runtime
missing/0 in horror_movies.csv. Never overwrites a known positive runtime.

Writes:
  data/runtime_imdb_basics_fill.csv   (sidecar report)
  data/horror_movies.csv              (runtime updates; append if absent)

Usage:
  python3 fill_runtime_imdb_basics.py
  python3 fill_runtime_imdb_basics.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import gzip
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
HM = DATA / "horror_movies.csv"
SIDECAR = DATA / "imdb_ids.csv"
POSTERS = DATA / "posters.csv"
BASICS_GZ = DATA / "imdb_datasets" / "title.basics.tsv.gz"
REPORT = DATA / "runtime_imdb_basics_fill.csv"


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


def load_tt_map() -> dict[int, str]:
    out: dict[int, str] = {}
    if not SIDECAR.exists():
        return out
    with SIDECAR.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, ValueError, TypeError):
                continue
            iid = (r.get("imdb_id") or "").strip()
            if iid.startswith("tt"):
                out[pid] = iid
    return out


def load_hm_runtime_title() -> dict[int, tuple[float, str]]:
    out: dict[int, tuple[float, str]] = {}
    if not HM.exists():
        return out
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, ValueError, TypeError):
                continue
            title = (r.get("title") or "").strip()
            out[pid] = (parse_runtime(r.get("runtime")), title)
    return out


def lookup_basics(want: set[str]) -> dict[str, tuple[int | None, str]]:
    """tconst -> (runtimeMinutes or None, titleType)."""
    if not BASICS_GZ.exists():
        raise SystemExit(f"missing {BASICS_GZ}")
    found: dict[str, tuple[int | None, str]] = {}
    with gzip.open(BASICS_GZ, "rt", encoding="utf-8", errors="replace") as f:
        header = f.readline().rstrip("\n").split("\t")
        idx = {h: i for i, h in enumerate(header)}
        for line in f:
            parts = line.rstrip("\n").split("\t")
            tconst = parts[idx["tconst"]]
            if tconst not in want:
                continue
            rm = parts[idx["runtimeMinutes"]]
            title_type = parts[idx["titleType"]]
            if rm != "\\N" and rm.isdigit() and int(rm) > 0:
                found[tconst] = (int(rm), title_type)
            else:
                found[tconst] = (None, title_type)
            if len(found) == len(want):
                break
    return found


def merge_runtimes(updates: dict[int, float], titles: dict[int, str]) -> tuple[int, int]:
    """Update runtime on existing HM rows; append minimal rows for new ids."""
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
            continue
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="write report only; do not modify horror_movies.csv",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="cap fills (0 = all)",
    )
    args = ap.parse_args()

    posters = load_poster_ids()
    tt_map = load_tt_map()
    hm = load_hm_runtime_title()

    targets: list[tuple[int, str, float, str]] = []
    for pid, title in posters.items():
        if pid not in tt_map:
            continue
        rt_before, hm_title = hm.get(pid, (0.0, ""))
        if rt_before < 0:
            continue  # text runtime — leave alone
        if rt_before > 0:
            continue
        targets.append((pid, tt_map[pid], rt_before, hm_title or title))

    print(
        f"posters={len(posters):,}  missing/0+tt={len(targets):,}  "
        f"(skipping positive/text runtimes)"
    )

    want = {tconst for _, tconst, _, _ in targets}
    print(f"looking up {len(want):,} tconsts in title.basics …")
    basics = lookup_basics(want)
    print(f"basics rows found={len(basics):,}")

    report_rows: list[dict] = []
    updates: dict[int, float] = {}
    titles: dict[int, str] = {}
    ok = no_rt = no_row = 0

    for pid, tconst, rt_before, title in sorted(targets, key=lambda x: x[0]):
        if tconst not in basics:
            no_row += 1
            report_rows.append(
                {
                    "id": pid,
                    "imdb_id": tconst,
                    "title": title,
                    "runtime_before": rt_before,
                    "runtime_after": "",
                    "titleType": "",
                    "status": "basics_miss",
                }
            )
            continue
        rt_imdb, title_type = basics[tconst]
        if rt_imdb is None or rt_imdb <= 0:
            no_rt += 1
            report_rows.append(
                {
                    "id": pid,
                    "imdb_id": tconst,
                    "title": title,
                    "runtime_before": rt_before,
                    "runtime_after": "",
                    "titleType": title_type,
                    "status": "basics_no_runtime",
                }
            )
            continue
        if args.limit and ok >= args.limit:
            report_rows.append(
                {
                    "id": pid,
                    "imdb_id": tconst,
                    "title": title,
                    "runtime_before": rt_before,
                    "runtime_after": rt_imdb,
                    "titleType": title_type,
                    "status": "skipped_limit",
                }
            )
            continue
        ok += 1
        updates[pid] = float(rt_imdb)
        titles[pid] = title
        report_rows.append(
            {
                "id": pid,
                "imdb_id": tconst,
                "title": title,
                "runtime_before": rt_before,
                "runtime_after": rt_imdb,
                "titleType": title_type,
                "status": "ok",
            }
        )

    fields = [
        "id",
        "imdb_id",
        "title",
        "runtime_before",
        "runtime_after",
        "titleType",
        "status",
    ]
    with REPORT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in report_rows:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"report → {REPORT} ({len(report_rows):,} rows)")
    print(f"status: ok={ok:,} basics_no_runtime={no_rt:,} basics_miss={no_row:,}")

    short = sum(
        1
        for r in report_rows
        if r["status"] == "ok" and int(r["runtime_after"]) <= 40
    )
    feat = ok - short
    print(f"  ok short≤40={short:,}  features>40={feat:,}")

    if args.dry_run:
        print("dry-run: horror_movies.csv unchanged")
        return

    updated, appended = merge_runtimes(updates, titles)
    print(f"horror_movies.csv: updated_runtime={updated} appended_new={appended}")

    # post-check coverage on posters
    hm2 = load_hm_runtime_title()
    have = sum(
        1 for pid in posters if pid in hm2 and hm2[pid][0] > 0
    )
    print(
        f"posters with runtime>0: {have:,}/{len(posters):,} "
        f"({100 * have / len(posters):.1f}%)"
    )


if __name__ == "__main__":
    main()
