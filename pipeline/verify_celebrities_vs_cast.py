#!/usr/bin/env python3
"""Cross-check Rekognition RecognizeCelebrities names against TMDB's actual movie credits.

If Rekognition finds a celebrity that isn't in the film's TMDB cast, that's a
strong signal the poster art was recycled from an unrelated photo (as found
with the "Cannon Fodder" / Brad Pitt case).

Usage:
  TMDB_API_KEY=... python3 verify_celebrities_vs_cast.py --workers 8
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).parent / "data"
OUT = DATA / "qa" / "celebrity_cast_verification.csv"
TMDB_CREDITS = "https://api.themoviedb.org/3/movie/{id}/credits"

FIELDS = ["id", "celeb_names", "cast_match", "unmatched_celebs", "error"]
_write_lock = threading.Lock()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def name_match(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() > 0.85


def load_done() -> set[int]:
    if not OUT.exists():
        return set()
    return set(int(r) for r in pd.read_csv(OUT)["id"])


def append_row(row: dict) -> None:
    new_file = not OUT.exists()
    with _write_lock:
        import csv

        with OUT.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            w.writerow(row)


def process_one(session: requests.Session, api_key: str, pid: int, names: list[str]) -> dict:
    try:
        r = session.get(TMDB_CREDITS.format(id=pid), params={"api_key": api_key}, timeout=20)
        data = r.json() if r.ok else {}
    except Exception as e:
        return {
            "id": pid,
            "celeb_names": json.dumps(names),
            "cast_match": "",
            "unmatched_celebs": "",
            "error": str(e),
        }

    cast_names = [c.get("name", "") for c in (data.get("cast") or [])]
    crew_names = [c.get("name", "") for c in (data.get("crew") or [])]
    all_names = cast_names + crew_names

    unmatched = []
    for n in names:
        if not any(name_match(n, c) for c in all_names):
            unmatched.append(n)

    return {
        "id": pid,
        "celeb_names": json.dumps(names, ensure_ascii=False),
        "cast_match": json.dumps([n for n in names if n not in unmatched], ensure_ascii=False),
        "unmatched_celebs": json.dumps(unmatched, ensure_ascii=False),
        "error": "",
    }


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.05)
    ap.add_argument(
        "--celebs-csv",
        default="",
        help="override data/celebrities.csv (e.g. data/qa/celebrities_thriller.csv)",
    )
    ap.add_argument("--out", default="", help="override output csv (keeps corpora separate)")
    args = ap.parse_args()
    if not args.api_key:
        raise SystemExit("Need TMDB_API_KEY")
    if args.out:
        OUT = Path(args.out)

    celebs = pd.read_csv(Path(args.celebs_csv) if args.celebs_csv else (DATA / "celebrities.csv"))
    celebs = celebs[celebs["n_celebs"] > 0].copy()
    celebs["names"] = celebs["names"].apply(json.loads)

    done = load_done()
    todo = celebs[~celebs["id"].isin(done)]
    print(f"target={len(celebs):,} done={len(done):,} todo={len(todo):,}")

    session = requests.Session()
    t0 = time.time()
    n_done = 0
    n_mismatch = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(process_one, session, args.api_key, int(r.id), r.names): r.id
            for r in todo.itertuples()
        }
        for fut in as_completed(futs):
            row = fut.result()
            append_row(row)
            n_done += 1
            unmatched = json.loads(row["unmatched_celebs"]) if row["unmatched_celebs"] else []
            if unmatched:
                n_mismatch += 1
            if n_done % 50 == 0:
                rate = n_done / max(time.time() - t0, 0.001)
                pct = 100 * n_mismatch / n_done
                print(
                    f"  {n_done:,}/{len(todo):,} mismatches={n_mismatch} ({pct:.0f}%) {rate:.1f}/s",
                    flush=True,
                )
                # aviso temprano, no al final: si a los primeros ~150 ya casi todo es
                # mismatch, es mucho mas probable un fallo silencioso (auth, filtro
                # mal puesto) que una senal real — exactamente lo que paso hoy con la
                # api key mal extraida (100% en vez de ~30%)
                if n_done == 150 and pct >= 90:
                    print(
                        f"  ⚠ AVISO: {pct:.0f}% mismatch en los primeros {n_done} — revisar antes de "
                        f"confiar en el resto (posible API key/auth/filtro roto)",
                        flush=True,
                    )
            time.sleep(args.delay)

    pct = 100 * n_mismatch / max(n_done, 1)
    print(f"\n=== DONE === processed={n_done:,} mismatches={n_mismatch:,} ({pct:.0f}%) -> {OUT}")


if __name__ == "__main__":
    main()
