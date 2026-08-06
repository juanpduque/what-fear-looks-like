#!/usr/bin/env python3
"""Fill residual zero/null runtimes for posters ∩ horror_movies.

Pipeline:
  1. Inventory residual (with/without tt, EN vs all)
  2. With tt: IMDb title.basics → OMDb Runtime → Wikidata P2047 → TMDB
  3. Without tt: Wikidata (P4947→P345+P2047) → IMDb suggest match →
     basics/OMDb/Wikidata/TMDB for newly matched ids → TMDB fallback
  4. Backup + merge into horror_movies.csv (+ imdb_ids.csv for new tt)
  5. Summary under data/qa/runtime_residual_fill/

Usage:
  python3 fill_runtime_residual.py
  python3 fill_runtime_residual.py --dry-run
  OMDB_API_KEY=... python3 fill_runtime_residual.py
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import random
import shutil
import time
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
HM = DATA / "horror_movies.csv"
SIDECAR = DATA / "imdb_ids.csv"
POSTERS = DATA / "posters.csv"
BASICS_GZ = DATA / "imdb_datasets" / "title.basics.tsv.gz"
OUT_DIR = DATA / "qa" / "runtime_residual_fill"

OMDB_URL = "http://www.omdbapi.com/"
WD_ENDPOINT = "https://query.wikidata.org/sparql"
WD_UA = "WhatFearLooksLike/1.0 (poster research; python-requests)"
TMDB_MOVIE = "https://api.themoviedb.org/3/movie/{pid}"

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
SUGGEST_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.imdb.com",
    "Referer": "https://www.imdb.com/",
}
PREFERRED_QID = frozenset({"movie", "tvMovie"})
PREFERRED_Q = frozenset({"feature", "TV movie"})
DEPRIORITIZED_QID = frozenset(
    {
        "short",
        "tvEpisode",
        "tvSeries",
        "videoGame",
        "podcastSeries",
        "musicVideo",
    }
)


def log(msg: str) -> None:
    print(msg, flush=True)


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
        return -1.0


def parse_omdb_runtime(raw: str | None) -> float:
    """'90 min' / '1 h 30 min' / 'N/A' → minutes."""
    if not raw:
        return 0.0
    s = str(raw).strip()
    if not s or s.upper() in {"N/A", "NA", "NULL"}:
        return 0.0
    # Prefer explicit "N min"
    import re

    m = re.search(r"(\d+)\s*min", s, re.I)
    if m:
        return float(m.group(1))
    h = re.search(r"(\d+)\s*h", s, re.I)
    mins = 0.0
    if h:
        mins += 60 * float(h.group(1))
    m2 = re.search(r"(\d+)\s*m(?!in)", s, re.I)
    if m2:
        mins += float(m2.group(1))
    if mins > 0:
        return mins
    try:
        v = float(s)
        return v if v > 0 else 0.0
    except ValueError:
        return 0.0


def auth_kwargs(api_key: str) -> dict:
    key = (api_key or "").strip()
    if key.startswith("eyJ"):
        return {"headers": {"Authorization": f"Bearer {key}"}}
    return {"params": {"api_key": key}}


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
    if SIDECAR.exists():
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


def load_hm_rows() -> dict[int, dict]:
    """id -> {runtime, lang, title, original_title, year, imdb_id}."""
    out: dict[int, dict] = {}
    if not HM.exists():
        return out
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, ValueError, TypeError):
                continue
            rd = (r.get("release_date") or "").strip()
            year = None
            if len(rd) >= 4 and rd[:4].isdigit():
                y = int(rd[:4])
                if 1888 <= y <= 2035:
                    year = y
            out[pid] = {
                "runtime": parse_runtime(r.get("runtime")),
                "lang": (r.get("original_language") or "").strip(),
                "title": (r.get("title") or "").strip(),
                "original_title": (r.get("original_title") or "").strip(),
                "year": year,
                "imdb_id": (r.get("imdb_id") or "").strip(),
            }
    return out


def write_sidecar(mapping: dict[int, str]) -> None:
    with SIDECAR.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "imdb_id"])
        w.writeheader()
        for pid in sorted(mapping):
            w.writerow({"id": pid, "imdb_id": mapping[pid]})


def merge_runtimes_and_tt(
    runtime_updates: dict[int, float],
    tt_updates: dict[int, str],
    titles: dict[int, str],
) -> tuple[int, int, int]:
    """Update runtime (+ imdb_id if empty). Returns (rt_upd, tt_upd, appended)."""
    if not HM.exists():
        raise SystemExit(f"missing {HM}")
    with HM.open(encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        if "id" not in fields or "runtime" not in fields:
            raise SystemExit(f"{HM} needs id and runtime columns")
        rows = list(reader)

    seen: set[int] = set()
    rt_upd = tt_upd = 0
    for row in rows:
        try:
            pid = int(row["id"])
        except (KeyError, ValueError, TypeError):
            continue
        seen.add(pid)
        if pid in runtime_updates:
            old = parse_runtime(row.get("runtime"))
            new_rt = runtime_updates[pid]
            if old <= 0 and new_rt > 0:
                row["runtime"] = str(
                    int(new_rt) if new_rt == int(new_rt) else new_rt
                )
                rt_upd += 1
        if pid in tt_updates and "imdb_id" in fields:
            cur = (row.get("imdb_id") or "").strip()
            if not cur.startswith("tt"):
                row["imdb_id"] = tt_updates[pid]
                tt_upd += 1

    appended = 0
    for pid, new_rt in sorted(runtime_updates.items()):
        if pid in seen or new_rt <= 0:
            continue
        row = {k: "" for k in fields}
        row["id"] = str(pid)
        row["runtime"] = str(int(new_rt) if new_rt == int(new_rt) else new_rt)
        if "title" in fields:
            row["title"] = titles.get(pid, "")
        if "original_title" in fields and not row.get("original_title"):
            row["original_title"] = titles.get(pid, "")
        if pid in tt_updates and "imdb_id" in fields:
            row["imdb_id"] = tt_updates[pid]
        rows.append(row)
        appended += 1

    tmp = HM.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(HM)
    return rt_upd, tt_upd, appended


def lookup_basics(want: set[str]) -> dict[str, tuple[int | None, str]]:
    if not BASICS_GZ.exists():
        log(f"WARN missing {BASICS_GZ}")
        return {}
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


def wd_duration_by_imdb(
    session: requests.Session, imdb_ids: list[str], batch: int = 80
) -> dict[str, float]:
    """P345 → P2047 (minutes)."""
    out: dict[str, float] = {}
    for start in range(0, len(imdb_ids), batch):
        chunk = imdb_ids[start : start + batch]
        values = " ".join(f'"{tt}"' for tt in chunk)
        query = (
            "SELECT ?imdb ?duration WHERE { "
            f"VALUES ?imdb {{ {values} }} "
            "?f wdt:P345 ?imdb . "
            "OPTIONAL { ?f wdt:P2047 ?duration . } "
            "}"
        )
        for attempt in range(5):
            try:
                r = session.get(
                    WD_ENDPOINT,
                    params={"query": query, "format": "json"},
                    headers={"User-Agent": WD_UA},
                    timeout=180,
                )
            except requests.RequestException:
                time.sleep(3 + attempt * 3)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(5 + attempt * 5)
                continue
            if not r.ok:
                log(f"  wikidata HTTP {r.status_code}: {r.text[:160]}")
                break
            for b in r.json()["results"]["bindings"]:
                imdb = b["imdb"]["value"].strip()
                if "duration" not in b:
                    continue
                try:
                    mins = float(b["duration"]["value"])
                except (KeyError, TypeError, ValueError):
                    continue
                # Heuristic: if > 1000 treat as seconds
                if mins > 1000:
                    mins = mins / 60.0
                if mins > 0:
                    out[imdb] = mins
            break
        done = min(start + batch, len(imdb_ids))
        log(f"  wikidata imdb duration {done}/{len(imdb_ids)} hits={len(out)}")
        time.sleep(1.0)
    return out


def wd_by_tmdb(
    session: requests.Session, tmdb_ids: list[int], batch: int = 80
) -> dict[int, tuple[str | None, float | None]]:
    """P4947 → (P345 imdb, P2047 duration)."""
    out: dict[int, tuple[str | None, float | None]] = {}
    for start in range(0, len(tmdb_ids), batch):
        chunk = tmdb_ids[start : start + batch]
        values = " ".join(f'"{i}"' for i in chunk)
        query = (
            "SELECT ?tmdb ?imdb ?duration WHERE { "
            f"VALUES ?tmdb {{ {values} }} "
            "?f wdt:P4947 ?tmdb . "
            "OPTIONAL { ?f wdt:P345 ?imdb . } "
            "OPTIONAL { ?f wdt:P2047 ?duration . } "
            "}"
        )
        for attempt in range(5):
            try:
                r = session.get(
                    WD_ENDPOINT,
                    params={"query": query, "format": "json"},
                    headers={"User-Agent": WD_UA},
                    timeout=180,
                )
            except requests.RequestException:
                time.sleep(3 + attempt * 3)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(5 + attempt * 5)
                continue
            if not r.ok:
                log(f"  wikidata HTTP {r.status_code}: {r.text[:160]}")
                break
            for b in r.json()["results"]["bindings"]:
                try:
                    tid = int(b["tmdb"]["value"])
                except (KeyError, ValueError):
                    continue
                imdb = None
                if "imdb" in b:
                    v = b["imdb"]["value"].strip()
                    if v.startswith("tt"):
                        imdb = v
                dur = None
                if "duration" in b:
                    try:
                        mins = float(b["duration"]["value"])
                        if mins > 1000:
                            mins = mins / 60.0
                        if mins > 0:
                            dur = mins
                    except (TypeError, ValueError):
                        pass
                prev = out.get(tid)
                if prev is None:
                    out[tid] = (imdb, dur)
                else:
                    # Prefer non-null fields
                    out[tid] = (imdb or prev[0], dur if dur is not None else prev[1])
            break
        done = min(start + batch, len(tmdb_ids))
        log(f"  wikidata tmdb {done}/{len(tmdb_ids)} rows={len(out)}")
        time.sleep(1.0)
    return out


def omdb_runtime(
    session: requests.Session, api_key: str, tt: str, delay: float
) -> float:
    try:
        r = session.get(
            OMDB_URL,
            params={"i": tt, "apikey": api_key},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if str(data.get("Response")).lower() == "false":
            time.sleep(delay)
            return 0.0
        mins = parse_omdb_runtime(data.get("Runtime"))
        time.sleep(delay)
        return mins
    except Exception:
        time.sleep(delay)
        return 0.0


def tmdb_runtime(
    session: requests.Session, api_key: str, pid: int
) -> float:
    url = TMDB_MOVIE.format(pid=pid)
    kwargs = auth_kwargs(api_key)
    for attempt in range(5):
        try:
            r = session.get(url, timeout=30, **kwargs)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code == 404:
            return 0.0
        if not r.ok:
            time.sleep(1 + attempt)
            continue
        raw = r.json().get("runtime")
        try:
            v = float(raw) if raw is not None else 0.0
            return v if v == v and v > 0 else 0.0
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def suggest_title(session: requests.Session, title: str) -> list[dict]:
    key = title.strip().lower()
    if not key:
        return []
    first = key[0] if key[0].isalnum() else "0"
    url = (
        f"https://v2.sg.media-imdb.com/suggestion/"
        f"{first}/{urllib.parse.quote(key)}.json"
    )
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            r = session.get(url, headers=SUGGEST_HEADERS, timeout=30)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 + attempt * 1.5)
                continue
            r.raise_for_status()
            return list(r.json().get("d") or [])
        except Exception as e:
            last_err = e
            time.sleep(1.0 + attempt * 1.2)
    if last_err:
        raise last_err
    return []


def is_preferred(item: dict) -> bool:
    qid = (item.get("qid") or "").strip()
    q = (item.get("q") or "").strip()
    if qid in PREFERRED_QID or q in PREFERRED_Q:
        return True
    if qid in DEPRIORITIZED_QID:
        return False
    return False


def title_matches(item_title: str, titles: list[str]) -> bool:
    it = (item_title or "").casefold().strip()
    if not it:
        return False
    return any(it == t.casefold().strip() for t in titles if t and t.strip())


def safe_suggest_match(
    titles: list[str], year: int, items: list[dict]
) -> tuple[str | None, str]:
    pool: list[dict] = []
    for x in items:
        tt = str(x.get("id") or "")
        if not tt.startswith("tt"):
            continue
        if not title_matches(str(x.get("l") or ""), titles):
            continue
        try:
            yi = int(x.get("y"))
        except (TypeError, ValueError):
            continue
        if yi != year:
            continue
        cand = {"imdb_id": tt, "qid": (x.get("qid") or "").strip(), "q": (x.get("q") or "").strip()}
        if not is_preferred(cand):
            continue
        pool.append(cand)
    by_tt = {c["imdb_id"]: c for c in pool}
    pool = list(by_tt.values())
    if not pool:
        return None, "no_title_year_match"
    if len(pool) == 1:
        return pool[0]["imdb_id"], "movie_exact_year"
    return None, f"ambiguous_n={len(pool)}"


def inventory(
    posters: dict[int, str], hm: dict[int, dict], tt: dict[int, str]
) -> dict:
    inter = set(posters) & set(hm)
    zero = []
    for pid in inter:
        rt = hm[pid]["runtime"]
        if rt < 0:
            continue  # text — leave alone
        if rt <= 0:
            zero.append(pid)
    with_tt = [p for p in zero if p in tt]
    no_tt = [p for p in zero if p not in tt]
    en_zero = [p for p in zero if hm[p]["lang"] == "en"]
    return {
        "posters": len(posters),
        "horror_movies": len(hm),
        "intersection": len(inter),
        "zero_runtime": len(zero),
        "zero_en": len(en_zero),
        "with_tt": len(with_tt),
        "with_tt_en": sum(1 for p in with_tt if hm[p]["lang"] == "en"),
        "without_tt": len(no_tt),
        "without_tt_en": sum(1 for p in no_tt if hm[p]["lang"] == "en"),
        "zero_ids": zero,
        "with_tt_ids": with_tt,
        "without_tt_ids": no_tt,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--omdb-key", default=os.environ.get("OMDB_API_KEY", ""))
    ap.add_argument("--tmdb-key", default=os.environ.get("TMDB_API_KEY", ""))
    ap.add_argument("--omdb-delay", type=float, default=0.25)
    ap.add_argument("--suggest-delay", type=float, default=0.35)
    ap.add_argument("--tmdb-delay", type=float, default=0.05)
    ap.add_argument("--wd-batch", type=int, default=80)
    ap.add_argument("--skip-suggest", action="store_true")
    ap.add_argument("--skip-omdb", action="store_true")
    ap.add_argument("--skip-wikidata", action="store_true")
    ap.add_argument("--skip-tmdb", action="store_true")
    ap.add_argument("--limit-with-tt", type=int, default=0)
    ap.add_argument("--limit-no-tt", type=int, default=0)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = datetime.now(timezone.utc).isoformat()

    posters = load_poster_ids()
    tt_map = load_tt_map()
    hm = load_hm_rows()
    # Prefer HM imdb_id if sidecar missing
    for pid, row in hm.items():
        iid = row["imdb_id"]
        if pid not in tt_map and iid.startswith("tt"):
            tt_map[pid] = iid

    inv = inventory(posters, hm, tt_map)
    inv_public = {k: v for k, v in inv.items() if not k.endswith("_ids")}
    log(f"INVENTORY {json.dumps(inv_public)}")
    with (OUT_DIR / "inventory_before.json").open("w", encoding="utf-8") as f:
        json.dump({**inv_public, "started": started}, f, indent=2)

    with_tt_ids = list(inv["with_tt_ids"])
    no_tt_ids = list(inv["without_tt_ids"])
    if args.limit_with_tt:
        with_tt_ids = with_tt_ids[: args.limit_with_tt]
    if args.limit_no_tt:
        no_tt_ids = no_tt_ids[: args.limit_no_tt]

    session = requests.Session()
    session.trust_env = False

    fills: list[dict] = []
    runtime_updates: dict[int, float] = {}
    tt_updates: dict[int, str] = {}
    titles: dict[int, str] = {}
    sources = Counter()

    def accept(pid: int, mins: float, source: str, imdb_id: str = "") -> None:
        if mins <= 0 or pid in runtime_updates:
            return
        runtime_updates[pid] = float(mins)
        titles[pid] = (
            hm.get(pid, {}).get("title")
            or posters.get(pid, "")
            or ""
        )
        sources[source] += 1
        fills.append(
            {
                "id": pid,
                "imdb_id": imdb_id or tt_map.get(pid, "") or tt_updates.get(pid, ""),
                "title": titles[pid],
                "lang": hm.get(pid, {}).get("lang", ""),
                "runtime_before": hm.get(pid, {}).get("runtime", 0),
                "runtime_after": int(mins) if mins == int(mins) else mins,
                "source": source,
                "cohort": "with_tt" if pid in inv["with_tt_ids"] else "without_tt",
            }
        )

    # ── Phase A: with tt ─────────────────────────────────────────────
    log(f"\n=== Phase A: with_tt n={len(with_tt_ids)} ===")
    want = {tt_map[p] for p in with_tt_ids}
    log(f"basics lookup {len(want)} …")
    basics = lookup_basics(want)
    basics_hit = 0
    still_need_tt: list[int] = []
    for pid in with_tt_ids:
        tconst = tt_map[pid]
        pair = basics.get(tconst)
        if pair and pair[0] and pair[0] > 0:
            accept(pid, float(pair[0]), "imdb_basics", tconst)
            basics_hit += 1
        else:
            still_need_tt.append(pid)
    log(f"basics filled={basics_hit} remaining={len(still_need_tt)}")

    # OMDb
    omdb_key = (args.omdb_key or "").strip()
    if args.skip_omdb:
        omdb_key = ""
    if omdb_key and still_need_tt:
        log(f"OMDb for {len(still_need_tt)} …")
        nxt: list[int] = []
        for i, pid in enumerate(still_need_tt, 1):
            tconst = tt_map[pid]
            mins = omdb_runtime(session, omdb_key, tconst, args.omdb_delay)
            if mins > 0:
                accept(pid, mins, "omdb", tconst)
            else:
                nxt.append(pid)
            if i % 50 == 0 or i == len(still_need_tt):
                log(f"  omdb {i}/{len(still_need_tt)} filled_so_far={sources['omdb']}")
        still_need_tt = nxt
    else:
        if not omdb_key:
            log("OMDb skipped (no OMDB_API_KEY)")

    # Wikidata P2047
    if not args.skip_wikidata and still_need_tt:
        log(f"Wikidata P2047 for {len(still_need_tt)} …")
        need_tt = [tt_map[p] for p in still_need_tt]
        wd = wd_duration_by_imdb(session, need_tt, batch=args.wd_batch)
        nxt = []
        for pid in still_need_tt:
            tconst = tt_map[pid]
            mins = wd.get(tconst, 0.0)
            if mins and mins > 0:
                accept(pid, mins, "wikidata_p2047", tconst)
            else:
                nxt.append(pid)
        still_need_tt = nxt
        log(f"wikidata remaining={len(still_need_tt)}")

    # TMDB fallback for with-tt
    tmdb_key = (args.tmdb_key or "").strip()
    if args.skip_tmdb:
        tmdb_key = ""
    if tmdb_key and still_need_tt:
        log(f"TMDB runtime for {len(still_need_tt)} with-tt …")
        nxt = []
        for i, pid in enumerate(still_need_tt, 1):
            mins = tmdb_runtime(session, tmdb_key, pid)
            if mins > 0:
                accept(pid, mins, "tmdb", tt_map[pid])
            else:
                nxt.append(pid)
            time.sleep(args.tmdb_delay)
            if i % 50 == 0 or i == len(still_need_tt):
                log(f"  tmdb {i}/{len(still_need_tt)} filled={sources['tmdb']}")
        still_need_tt = nxt
    elif not tmdb_key:
        log("TMDB skipped (no TMDB_API_KEY)")

    with_tt_still = set(still_need_tt)

    # ── Phase B: without tt ──────────────────────────────────────────
    log(f"\n=== Phase B: without_tt n={len(no_tt_ids)} ===")
    still_no = list(no_tt_ids)

    # Wikidata via TMDB id
    if not args.skip_wikidata and still_no:
        log(f"Wikidata by TMDB for {len(still_no)} …")
        wd2 = wd_by_tmdb(session, still_no, batch=args.wd_batch)
        nxt = []
        for pid in still_no:
            imdb, dur = wd2.get(pid, (None, None))
            if imdb and pid not in tt_map:
                tt_updates[pid] = imdb
                tt_map[pid] = imdb
            if dur and dur > 0:
                accept(pid, dur, "wikidata_tmdb_p2047", imdb or "")
            elif imdb:
                # try basics for newly found tt
                nxt.append(pid)
            else:
                nxt.append(pid)
        # For those with new tt but no duration yet, try basics/omdb/wd
        newly = [p for p in nxt if p in tt_map and p not in runtime_updates]
        if newly:
            want2 = {tt_map[p] for p in newly}
            basics2 = lookup_basics(want2)
            still2 = []
            for pid in newly:
                pair = basics2.get(tt_map[pid])
                if pair and pair[0] and pair[0] > 0:
                    accept(pid, float(pair[0]), "imdb_basics_after_wd_tt", tt_map[pid])
                else:
                    still2.append(pid)
            if omdb_key and still2:
                s3 = []
                for pid in still2:
                    mins = omdb_runtime(session, omdb_key, tt_map[pid], args.omdb_delay)
                    if mins > 0:
                        accept(pid, mins, "omdb_after_wd_tt", tt_map[pid])
                    else:
                        s3.append(pid)
                still2 = s3
            if not args.skip_wikidata and still2:
                wd3 = wd_duration_by_imdb(
                    session, [tt_map[p] for p in still2], batch=args.wd_batch
                )
                s4 = []
                for pid in still2:
                    mins = wd3.get(tt_map[pid], 0.0)
                    if mins > 0:
                        accept(pid, mins, "wikidata_p2047_after_wd_tt", tt_map[pid])
                    else:
                        s4.append(pid)
                still2 = s4
            # rebuild still_no: not filled
            still_no = [p for p in nxt if p not in runtime_updates]
        else:
            still_no = [p for p in nxt if p not in runtime_updates]
        log(f"after wikidata-tmdb remaining={len(still_no)}")

    # IMDb suggest match
    if not args.skip_suggest and still_no:
        log(f"IMDb suggest for {len(still_no)} …")
        suggest_hits = 0
        matched_need_rt: list[int] = []
        nxt = []
        for i, pid in enumerate(still_no, 1):
            row = hm.get(pid, {})
            year = row.get("year")
            title = row.get("title") or posters.get(pid, "")
            ot = row.get("original_title") or ""
            if year is None:
                nxt.append(pid)
                fills.append(
                    {
                        "id": pid,
                        "imdb_id": "",
                        "title": title,
                        "lang": row.get("lang", ""),
                        "runtime_before": row.get("runtime", 0),
                        "runtime_after": "",
                        "source": "suggest_skip_no_year",
                        "cohort": "without_tt",
                    }
                )
                continue
            titles_q = []
            for t in (title, ot):
                t = (t or "").strip()
                if t and t not in titles_q:
                    titles_q.append(t)
            items: list[dict] = []
            seen_tt: set[str] = set()
            err = None
            for q in titles_q:
                try:
                    for x in suggest_title(session, q):
                        tid = str(x.get("id") or "")
                        if tid in seen_tt:
                            continue
                        seen_tt.add(tid)
                        items.append(x)
                except Exception as e:
                    err = f"suggest_err_{type(e).__name__}"
                    break
                if len(titles_q) > 1:
                    time.sleep(0.15)
            if err:
                nxt.append(pid)
                if i % 25 == 0:
                    log(f"  suggest {i}/{len(still_no)} ERR {pid} {err}")
                time.sleep(args.suggest_delay + random.uniform(0, 0.2))
                continue
            winner, reason = safe_suggest_match(titles_q, int(year), items)
            if winner:
                tt_updates[pid] = winner
                tt_map[pid] = winner
                matched_need_rt.append(pid)
                suggest_hits += 1
                log(f"  suggest OK {pid} {winner} {title!r} ({reason})")
            else:
                nxt.append(pid)
                if i % 25 == 0 or reason.startswith("ambiguous"):
                    log(f"  suggest MISS {pid} {title!r} {year} {reason}")
            time.sleep(args.suggest_delay + random.uniform(0, 0.2))
            if i % 40 == 0:
                log(f"  suggest progress {i}/{len(still_no)} hits={suggest_hits}")

        # Resolve runtime for suggest matches
        if matched_need_rt:
            want3 = {tt_map[p] for p in matched_need_rt}
            basics3 = lookup_basics(want3)
            rem = []
            for pid in matched_need_rt:
                pair = basics3.get(tt_map[pid])
                if pair and pair[0] and pair[0] > 0:
                    accept(pid, float(pair[0]), "imdb_basics_after_suggest", tt_map[pid])
                else:
                    rem.append(pid)
            if omdb_key and rem:
                rem2 = []
                for pid in rem:
                    mins = omdb_runtime(session, omdb_key, tt_map[pid], args.omdb_delay)
                    if mins > 0:
                        accept(pid, mins, "omdb_after_suggest", tt_map[pid])
                    else:
                        rem2.append(pid)
                rem = rem2
            if not args.skip_wikidata and rem:
                wd4 = wd_duration_by_imdb(
                    session, [tt_map[p] for p in rem], batch=args.wd_batch
                )
                rem2 = []
                for pid in rem:
                    mins = wd4.get(tt_map[pid], 0.0)
                    if mins > 0:
                        accept(pid, mins, "wikidata_p2047_after_suggest", tt_map[pid])
                    else:
                        rem2.append(pid)
                rem = rem2
            if tmdb_key and rem:
                rem2 = []
                for pid in rem:
                    mins = tmdb_runtime(session, tmdb_key, pid)
                    if mins > 0:
                        accept(pid, mins, "tmdb_after_suggest", tt_map[pid])
                    else:
                        rem2.append(pid)
                    time.sleep(args.tmdb_delay)
                rem = rem2
            nxt.extend(rem)
        still_no = [p for p in nxt if p not in runtime_updates]
        log(f"after suggest remaining={len(still_no)} hits={suggest_hits}")

    # TMDB fallback for remaining no-tt
    if tmdb_key and still_no:
        log(f"TMDB fallback for {len(still_no)} no-tt …")
        nxt = []
        for i, pid in enumerate(still_no, 1):
            mins = tmdb_runtime(session, tmdb_key, pid)
            if mins > 0:
                accept(pid, mins, "tmdb", tt_map.get(pid, ""))
            else:
                nxt.append(pid)
            time.sleep(args.tmdb_delay)
            if i % 50 == 0 or i == len(still_no):
                log(f"  tmdb-no-tt {i}/{len(still_no)}")
        still_no = nxt

    without_tt_still = set(still_no)

    # ── Persist ──────────────────────────────────────────────────────
    fill_path = OUT_DIR / "fills.csv"
    fields = [
        "id",
        "imdb_id",
        "title",
        "lang",
        "runtime_before",
        "runtime_after",
        "source",
        "cohort",
    ]
    # Deduplicate fills: keep successful accepts + skip notes without overwrite
    seen_fill: set[int] = set()
    ordered: list[dict] = []
    for row in fills:
        pid = int(row["id"])
        if pid in runtime_updates and row.get("runtime_after") in ("", None):
            continue
        if pid in seen_fill and row.get("runtime_after") not in ("", None):
            # replace prior skip
            ordered = [r for r in ordered if int(r["id"]) != pid]
            seen_fill.discard(pid)
        if pid in seen_fill:
            continue
        seen_fill.add(pid)
        ordered.append(row)
    # Ensure every accepted fill is present
    have = {int(r["id"]) for r in ordered if r.get("runtime_after") not in ("", None)}
    for row in fills:
        if int(row["id"]) in runtime_updates and int(row["id"]) not in have:
            if row.get("runtime_after") not in ("", None):
                ordered.append(row)
                have.add(int(row["id"]))

    with fill_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in sorted(ordered, key=lambda x: int(x["id"])):
            w.writerow({k: r.get(k, "") for k in fields})

    still_zero_ids = sorted(with_tt_still | without_tt_still)
    still_path = OUT_DIR / "still_zero.csv"
    with still_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["id", "title", "lang", "imdb_id", "year", "cohort"],
        )
        w.writeheader()
        for pid in still_zero_ids:
            row = hm.get(pid, {})
            w.writerow(
                {
                    "id": pid,
                    "title": row.get("title") or posters.get(pid, ""),
                    "lang": row.get("lang", ""),
                    "imdb_id": tt_map.get(pid, ""),
                    "year": row.get("year") or "",
                    "cohort": "with_tt" if pid in with_tt_still else "without_tt",
                }
            )

    backup_path = None
    hm_rt_upd = hm_tt_upd = hm_app = 0
    if not args.dry_run and (runtime_updates or tt_updates):
        backup_path = OUT_DIR / f"horror_movies.bak_{ts}.csv"
        shutil.copy2(HM, backup_path)
        log(f"backup → {backup_path}")
        # Merge sidecar tt
        if tt_updates:
            full_map = load_tt_map()
            full_map.update(tt_updates)
            # also keep existing
            for pid, iid in tt_map.items():
                if iid.startswith("tt"):
                    full_map[pid] = iid
            write_sidecar(full_map)
            log(f"sidecar updated (+{len(tt_updates)} tt)")
        hm_rt_upd, hm_tt_upd, hm_app = merge_runtimes_and_tt(
            runtime_updates, tt_updates, titles
        )
        log(
            f"horror_movies: runtime_updated={hm_rt_upd} "
            f"imdb_updated={hm_tt_upd} appended={hm_app}"
        )
    elif args.dry_run:
        log("dry-run: no writes to horror_movies / imdb_ids")

    # Post inventory
    hm2 = load_hm_rows()
    tt2 = load_tt_map()
    for pid, row in hm2.items():
        iid = row["imdb_id"]
        if pid not in tt2 and iid.startswith("tt"):
            tt2[pid] = iid
    inv_after = inventory(posters, hm2, tt2)
    inv_after_public = {k: v for k, v in inv_after.items() if not k.endswith("_ids")}

    summary = {
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(args.dry_run),
        "omdb_available": bool(omdb_key),
        "tmdb_available": bool(tmdb_key),
        "inventory_before": inv_public,
        "inventory_after": inv_after_public,
        "attempted": {
            "with_tt": len(with_tt_ids),
            "without_tt": len(no_tt_ids),
            "total": len(with_tt_ids) + len(no_tt_ids),
        },
        "filled": len(runtime_updates),
        "filled_by_source": dict(sources),
        "tt_newly_matched": len(tt_updates),
        "still_zero": len(still_zero_ids),
        "still_zero_with_tt": len(with_tt_still),
        "still_zero_without_tt": len(without_tt_still),
        "horror_movies_updates": {
            "runtime_updated": hm_rt_upd,
            "imdb_updated": hm_tt_upd,
            "appended": hm_app,
        },
        "paths": {
            "fills": str(fill_path),
            "still_zero": str(still_path),
            "backup": str(backup_path) if backup_path else None,
            "out_dir": str(OUT_DIR),
        },
        "blockers": [],
    }
    if not omdb_key:
        summary["blockers"].append(
            "OMDB_API_KEY missing — skipped OMDb Runtime path"
        )
    if not tmdb_key:
        summary["blockers"].append("TMDB_API_KEY missing — skipped TMDB fallback")

    with (OUT_DIR / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    md = OUT_DIR / "SUMMARY.md"
    md.write_text(
        "\n".join(
            [
                "# Runtime residual fill",
                "",
                f"- Started: `{summary['started']}`",
                f"- Finished: `{summary['finished']}`",
                f"- Dry-run: `{summary['dry_run']}`",
                "",
                "## Inventory",
                "",
                f"- Before zero: **{inv_public['zero_runtime']}** "
                f"(EN {inv_public['zero_en']}) — "
                f"with_tt {inv_public['with_tt']} / without_tt {inv_public['without_tt']}",
                f"- After zero: **{inv_after_public['zero_runtime']}** "
                f"(EN {inv_after_public['zero_en']}) — "
                f"with_tt {inv_after_public['with_tt']} / "
                f"without_tt {inv_after_public['without_tt']}",
                "",
                "## Results",
                "",
                f"- Attempted: {summary['attempted']['total']}",
                f"- Filled: **{summary['filled']}**",
                f"- Still zero: **{summary['still_zero']}** "
                f"(with_tt {summary['still_zero_with_tt']}, "
                f"without_tt {summary['still_zero_without_tt']})",
                f"- New IMDb ids: {summary['tt_newly_matched']}",
                f"- Sources: `{json.dumps(summary['filled_by_source'])}`",
                "",
                "## Blockers",
                "",
            ]
            + (
                [f"- {b}" for b in summary["blockers"]]
                if summary["blockers"]
                else ["- (none)"]
            )
            + [
                "",
                "## Paths",
                "",
                f"- Fills: `{fill_path}`",
                f"- Still zero: `{still_path}`",
                f"- Backup: `{backup_path}`",
                f"- Summary JSON: `{OUT_DIR / 'summary.json'}`",
                "",
            ]
        ),
        encoding="utf-8",
    )

    log("\n=== DONE ===")
    log(json.dumps({k: summary[k] for k in (
        "filled", "still_zero", "filled_by_source", "tt_newly_matched",
        "inventory_before", "inventory_after", "blockers"
    )}, indent=2))


if __name__ == "__main__":
    main()
