#!/usr/bin/env python3
"""Fallback IMDb ids from Wikidata for TMDB ids that /external_ids left blank.

Matches on TMDB film ID (P4947) and reads IMDb ID (P345). Free, no daily quota,
so it is the cheapest second pass after enrich_imdb_ids.py.

Writes:
  data/imdb_ids.csv          (sidecar id,imdb_id — updated in place)
  data/imdb_ids_wikidata.csv (just the ids this pass recovered)

Usage:
  python3 enrich_imdb_wikidata.py
  python3 enrich_imdb_wikidata.py --batch 400 --dry-run
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
SIDECAR = DATA / "imdb_ids.csv"
POSTERS = DATA / "posters.csv"
HITS_OUT = DATA / "imdb_ids_wikidata.csv"

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "AnatomyOfFear/1.0 (poster research; python-requests)"
QUERY = "SELECT ?tmdb ?imdb WHERE {{ VALUES ?tmdb {{ {values} }} " \
        "?f wdt:P4947 ?tmdb ; wdt:P345 ?imdb . }}"


def load_sidecar() -> dict[int, str]:
    out: dict[int, str] = {}
    if not SIDECAR.exists():
        return out
    with SIDECAR.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out[int(r["id"])] = (r.get("imdb_id") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue
    return out


def load_corpus() -> list[int]:
    out, seen = [], set()
    with POSTERS.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if pid not in seen:
                seen.add(pid)
                out.append(pid)
    return out


def query_batch(session: requests.Session, ids: list[int]) -> dict[int, str]:
    values = " ".join(f'"{i}"' for i in ids)
    for attempt in range(4):
        try:
            r = session.get(
                ENDPOINT,
                params={"query": QUERY.format(values=values), "format": "json"},
                headers={"User-Agent": UA},
                timeout=180,
            )
        except requests.RequestException:
            time.sleep(3 + attempt * 3)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(5 + attempt * 5)
            continue
        if not r.ok:
            print(f"  wikidata HTTP {r.status_code}: {r.text[:160]}")
            return {}
        out: dict[int, str] = {}
        for b in r.json()["results"]["bindings"]:
            imdb = b["imdb"]["value"].strip()
            if not imdb.startswith("tt"):
                continue
            try:
                out[int(b["tmdb"]["value"])] = imdb
            except ValueError:
                continue
        return out
    return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=400)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="do not touch the sidecar")
    args = ap.parse_args()

    if not POSTERS.exists():
        raise SystemExit(f"missing {POSTERS}")

    sidecar = load_sidecar()
    todo = [i for i in load_corpus() if not sidecar.get(i, "").startswith("tt")]
    if args.limit:
        todo = todo[: args.limit]
    print(f"corpus ids without imdb_id: {len(todo):,}")

    session = requests.Session()
    found: dict[int, str] = {}
    for start in range(0, len(todo), args.batch):
        chunk = todo[start : start + args.batch]
        found.update(query_batch(session, chunk))
        done = min(start + args.batch, len(todo))
        print(f"  {done}/{len(todo)} recovered={len(found):,}", flush=True)
        time.sleep(args.sleep)

    print(f"\nwikidata recovered {len(found):,} / {len(todo):,} "
          f"({100 * len(found) / max(len(todo), 1):.1f}%)")
    if not found or args.dry_run:
        return

    with HITS_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "imdb_id"])
        w.writeheader()
        for pid in sorted(found):
            w.writerow({"id": pid, "imdb_id": found[pid]})

    sidecar.update(found)
    with SIDECAR.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "imdb_id"])
        w.writeheader()
        for pid in sorted(sidecar):
            w.writerow({"id": pid, "imdb_id": sidecar[pid]})
    print(f"sidecar → {SIDECAR.name} ({len(sidecar):,} rows)")


if __name__ == "__main__":
    main()
