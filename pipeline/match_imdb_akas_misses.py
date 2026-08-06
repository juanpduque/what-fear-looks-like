#!/usr/bin/env python3
"""AKA-aware IMDb rematch for feature misses (selenium + residuals).

Recovers tt… ids by matching corpus title / original_title (and optionally
TMDB alternative_titles) against IMDb title.akas + title.basics.

Match rules:
  - normalized title equality (accents/punct stripped, leading 'the ' dropped)
  - titleType in movie / tvMovie (video only as fallback)
  - year exact, else ±1, else ±2; targets without year are scored but not
    auto-applied
  - prefer US / GB / null-region AKAs; score and accept only unique best
    (or single Horror-genre candidate among ties)

Writes under data/qa/imdb_akas_rematch/:
  hits.csv, miss.csv, ambiguous.csv, applied.csv, summary.json

Usage:
  python3 match_imdb_akas_misses.py
  python3 match_imdb_akas_misses.py --dry-run
  python3 match_imdb_akas_misses.py --no-tmdb
  python3 match_imdb_akas_misses.py --also-missing-features
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import shutil
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from enrich_imdb_ids import (
    DATA,
    HM,
    SIDECAR,
    auth_kwargs,
    load_sidecar,
    merge_into_horror_movies,
    write_sidecar,
)
from match_imdb_title_basics_features import (
    PREFERRED_TYPES,
    FALLBACK_TYPES,
    EXCLUDED_TYPES,
    normalize_title,
    parse_year,
    is_horror,
    valid_tt,
)

AKAS_GZ = DATA / "imdb_datasets" / "title.akas.tsv.gz"
BASICS_GZ = DATA / "imdb_datasets" / "title.basics.tsv.gz"

SELENIUM_MISS = DATA / "imdb_selenium_features_miss.csv"
MISSING_FEATURES = DATA / "qa" / "missing_imdb_id_features.csv"

OUT_DIR = DATA / "qa" / "imdb_akas_rematch"
HITS_OUT = OUT_DIR / "hits.csv"
MISS_OUT = OUT_DIR / "miss.csv"
AMBIG_OUT = OUT_DIR / "ambiguous.csv"
APPLIED_OUT = OUT_DIR / "applied.csv"
SUMMARY_OUT = OUT_DIR / "summary.json"
TMDB_CACHE = OUT_DIR / "tmdb_alt_titles_cache.json"
HM_BACKUP = OUT_DIR / "horror_movies.csv.bak_before_akas_rematch"

PREFERRED_REGIONS = {"US": 3, "GB": 2, "XWW": 2, "": 1, "\\N": 1}
YEAR_TOLERANCE = 2
ALT_URL = "https://api.themoviedb.org/3/movie/{pid}/alternative_titles"


def load_dotenv_files() -> None:
    """Load TMDB_API_KEY from common .env locations if not already set."""
    if (os.environ.get("TMDB_API_KEY") or "").strip():
        return
    root = Path(__file__).resolve().parent
    for path in (root / ".env.local", root.parent / ".env", root / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            if k.strip() == "TMDB_API_KEY" and v.strip():
                os.environ.setdefault("TMDB_API_KEY", v.strip().strip("\"'"))
                return
    for cand in (
        DATA / "qa" / "tmdb_api_key",
        DATA / "qa" / "_imdb_selenium_stage" / "input" / "qa" / "tmdb_api_key",
    ):
        if cand.exists():
            key = cand.read_text(encoding="utf-8").strip()
            if key:
                os.environ.setdefault("TMDB_API_KEY", key)
                return


def get_tmdb_key(explicit: str = "") -> str:
    load_dotenv_files()
    return (explicit or os.environ.get("TMDB_API_KEY") or "").strip()


def load_hm_meta(ids: set[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not HM.exists():
        return out
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (TypeError, ValueError):
                continue
            if pid not in ids:
                continue
            year = None
            rd = (r.get("release_date") or "")[:4]
            if rd.isdigit():
                year = int(rd)
            out[pid] = {
                "title": (r.get("title") or "").strip(),
                "original_title": (r.get("original_title") or "").strip(),
                "year": year,
                "imdb_id": (r.get("imdb_id") or "").strip(),
                "runtime": (r.get("runtime") or "").strip(),
            }
    return out


def load_targets(
    *,
    also_missing_features: bool,
    limit: int,
    include_already_tt: bool,
) -> list[dict]:
    """Build rematch targets from selenium miss (+ optional residual CSV)."""
    sidecar = load_sidecar()
    rows: list[dict] = []
    seen: set[int] = set()

    def add_row(pid: int, title: str, year: int | None, source: str) -> None:
        if pid in seen:
            return
        seen.add(pid)
        rows.append(
            {
                "id": pid,
                "title_hint": title,
                "year_hint": year,
                "source_list": source,
            }
        )

    if SELENIUM_MISS.exists():
        with SELENIUM_MISS.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                add_row(pid, (r.get("title") or "").strip(), parse_year(r.get("year")), "selenium_miss")

    if also_missing_features and MISSING_FEATURES.exists():
        with MISSING_FEATURES.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                add_row(
                    pid,
                    (r.get("title") or "").strip(),
                    parse_year(r.get("year")),
                    "missing_imdb_id_features",
                )

    hm = load_hm_meta(seen)
    targets: list[dict] = []
    skipped_have_tt = 0
    synced_hm_to_sidecar = 0
    for row in rows:
        pid = row["id"]
        meta = hm.get(pid, {})
        hm_tt = meta.get("imdb_id") or ""
        sc_tt = sidecar.get(pid, "") or ""
        # HM has tt but sidecar empty → sync (e.g. Love Me Dead / Issac)
        if valid_tt(hm_tt) and not valid_tt(sc_tt):
            sidecar[pid] = hm_tt
            synced_hm_to_sidecar += 1
            sc_tt = hm_tt
        existing = hm_tt if valid_tt(hm_tt) else sc_tt
        if valid_tt(existing) and not include_already_tt:
            skipped_have_tt += 1
            continue
        title = meta.get("title") or row["title_hint"] or ""
        original = meta.get("original_title") or ""
        year = meta.get("year") if meta.get("year") is not None else row["year_hint"]
        targets.append(
            {
                "id": pid,
                "title": title,
                "original_title": original,
                "year": year,
                "source_list": row["source_list"],
                "existing_imdb_id": existing if valid_tt(existing) else "",
                "query_titles": [],  # filled later
                "tmdb_alts": [],
            }
        )
    if synced_hm_to_sidecar:
        write_sidecar(sidecar)
        print(f"synced {synced_hm_to_sidecar:,} HM→sidecar tt for miss-list ids")
    if limit:
        targets = targets[:limit]
    print(f"loaded targets: {len(targets):,} (skipped already-tt: {skipped_have_tt:,})")
    return targets


def region_score(region: str) -> int:
    r = (region or "").strip()
    if r in PREFERRED_REGIONS:
        return PREFERRED_REGIONS[r]
    if r in ("", "\\N"):
        return 1
    return 0


def cheap_key(s: str) -> str:
    """Fast ASCII-ish key: lower, alnum/space only, drop leading 'the '."""
    if not s:
        return ""
    out: list[str] = []
    prev_space = True
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
            prev_space = False
        elif not prev_space:
            out.append(" ")
            prev_space = True
    key = "".join(out).strip()
    if key.startswith("the "):
        key = key[4:].strip()
    return key


def scan_akas(akas_path: Path, lookup: dict[str, str]) -> dict[str, list[dict]]:
    """Stream title.akas; keep rows whose title.casefold() is in lookup.

    lookup maps casefold(title_variant) → canonical normalize_title key.
    """
    by_norm: dict[str, list[dict]] = defaultdict(list)
    n_rows = 0
    n_hits = 0
    with gzip.open(akas_path, "rt", encoding="utf-8", errors="replace") as f:
        f.readline()  # header
        for line in f:
            n_rows += 1
            if n_rows % 5_000_000 == 0:
                print(f"  … akas scanned {n_rows:,} rows ({n_hits:,} hits)")
            i1 = line.find("\t")
            if i1 < 0:
                continue
            i2 = line.find("\t", i1 + 1)
            if i2 < 0:
                continue
            i3 = line.find("\t", i2 + 1)
            if i3 < 0:
                continue
            title = line[i2 + 1 : i3]
            if not title:
                continue
            norm = lookup.get(title.casefold())
            if not norm:
                continue

            rest = line[i3 + 1 :].rstrip("\n").split("\t")
            if len(rest) < 5:
                continue
            n_hits += 1
            region = rest[0]
            types = rest[2]
            is_orig = rest[4].strip() == "1"
            if region == "\\N":
                region = ""
            if types == "\\N":
                types = ""
            by_norm[norm].append(
                {
                    "tconst": line[:i1],
                    "aka_title": title,
                    "region": region,
                    "types": types,
                    "is_original": is_orig,
                    "region_score": region_score(region),
                    "source": "akas",
                    "matched_norm": norm,
                }
            )
    print(f"  akas done: {n_rows:,} rows, {n_hits:,} hits across {len(by_norm):,} norms")
    return by_norm


def expand_needed_keys(raw_titles: list[str]) -> set[str]:
    """Canonical norms plus casefold/cheap variants used as AKA lookup keys."""
    needed: set[str] = set()
    for raw in raw_titles:
        s = (raw or "").strip()
        if not s:
            continue
        n = normalize_title(s)
        if not n:
            continue
        needed.add(n)
        # Also index the raw casefold / cheap forms so AKA casefold hits resolve
        # back to the same canonical norm via lookup[title.casefold()] = n
        # (scan_akas maps casefold → norm; we store norms in `needed` and build
        # the casefold map from both norms and raw strings below).
    return needed


def build_akas_lookup(raw_titles: list[str], needed: set[str]) -> dict[str, str]:
    """casefold(title_variant) → canonical norm for AKA streaming."""
    lookup: dict[str, str] = {}
    for n in needed:
        lookup[n.casefold()] = n
    for raw in raw_titles:
        s = (raw or "").strip()
        if not s:
            continue
        n = normalize_title(s)
        if not n or n not in needed:
            continue
        lookup[s.casefold()] = n
        ck = cheap_key(s)
        if ck:
            lookup[ck] = n
        # common light variants
        lookup[s.replace(":", "").casefold()] = n
        lookup[s.replace(" - ", " ").casefold()] = n
    return lookup


def scan_basics(
    basics_path: Path,
    needed: set[str],
    aka_tconsts: set[str],
) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """Stream title.basics for title matches + metadata for AKA tconsts."""
    by_norm: dict[str, list[dict]] = defaultdict(list)
    meta: dict[str, dict] = {}
    n_rows = 0
    with gzip.open(basics_path, "rt", encoding="utf-8", errors="replace") as f:
        f.readline()  # header
        for line in f:
            n_rows += 1
            if n_rows % 2_000_000 == 0:
                print(f"  … basics scanned {n_rows:,} rows (meta={len(meta):,})")
            parts = line.split("\t")
            if len(parts) < 9:
                continue
            # tconst, titleType, primaryTitle, originalTitle, isAdult, startYear, endYear, runtimeMinutes, genres
            ttype = parts[1]
            if ttype in EXCLUDED_TYPES:
                continue
            if ttype not in PREFERRED_TYPES and ttype not in FALLBACK_TYPES:
                continue
            tconst = parts[0]
            pt_raw = parts[2]
            ot_raw = parts[3]
            pt = normalize_title(pt_raw)
            ot = normalize_title(ot_raw)
            want_meta = tconst in aka_tconsts or (pt and pt in needed) or (ot and ot in needed)
            if not want_meta:
                continue
            genres = parts[8].strip()
            info = {
                "tconst": tconst,
                "titleType": ttype,
                "primaryTitle": pt_raw,
                "originalTitle": ot_raw,
                "startYear": parse_year(parts[5]),
                "genres": genres,
                "is_horror": is_horror(genres),
            }
            meta[tconst] = info
            hit_keys = set()
            if pt and pt in needed:
                hit_keys.add(pt)
            if ot and ot in needed:
                hit_keys.add(ot)
            for k in hit_keys:
                by_norm[k].append(
                    {
                        "tconst": tconst,
                        "aka_title": pt_raw if k == pt else ot_raw,
                        "region": "",
                        "types": "basics",
                        "is_original": k == ot and bool(ot),
                        "region_score": 1,
                        "source": "basics",
                        "matched_norm": k,
                    }
                )
    print(
        f"  basics done: {n_rows:,} rows; "
        f"{len(meta):,} title metas; {sum(len(v) for v in by_norm.values()):,} title hits"
    )
    return by_norm, meta


def year_ok(cand_year: int | None, target_year: int | None, tol: int) -> tuple[bool, int | None]:
    """Return (ok, abs_delta). delta None if target has no year."""
    if target_year is None:
        return True, None
    if cand_year is None:
        return False, None
    d = abs(cand_year - target_year)
    return d <= tol, d


def score_candidate(
    hit: dict,
    info: dict,
    target_year: int | None,
    year_delta: int | None,
) -> tuple[int, tuple]:
    """Higher is better. Tie-break tuple for stable unique-best detection."""
    score = 0
    src = hit.get("source") or ""
    if src == "akas":
        score += 10 + int(hit.get("region_score") or 0)
        if hit.get("is_original"):
            score += 2
        types = (hit.get("types") or "").lower()
        if "imdbdisplay" in types:
            score += 3
        if "original" in types:
            score += 2
    elif src == "basics":
        score += 8
    elif src == "tmdb_alt+akas":
        score += 12 + int(hit.get("region_score") or 0)
    elif src == "tmdb_alt+basics":
        score += 9

    ttype = info.get("titleType") or ""
    if ttype == "movie":
        score += 5
    elif ttype == "tvMovie":
        score += 3
    elif ttype == "video":
        score += 1

    if info.get("is_horror"):
        score += 4

    if year_delta is None:
        score -= 3  # no target year → less confidence
    elif year_delta == 0:
        score += 6
    elif year_delta == 1:
        score += 3
    elif year_delta == 2:
        score += 1

    # sort key: score desc, year_delta asc, region_score desc, tconst asc
    tie = (
        -score,
        year_delta if year_delta is not None else 99,
        -int(hit.get("region_score") or 0),
        info.get("tconst") or "",
    )
    return score, tie


def gather_candidates(
    target: dict,
    by_norm_akas: dict[str, list[dict]],
    by_norm_basics: dict[str, list[dict]],
    meta: dict[str, dict],
    *,
    tmdb_norm_set: set[str] | None = None,
) -> list[dict]:
    """Pool AKA + basics hits for this target's query norms; attach meta/score."""
    norms: list[str] = []
    for raw in target.get("query_titles") or []:
        n = normalize_title(raw)
        if n and n not in norms:
            norms.append(n)

    pooled: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()  # (tconst, source_family)

    for n in norms:
        from_tmdb = bool(tmdb_norm_set and n in tmdb_norm_set)
        for hit in by_norm_akas.get(n, []):
            src = "tmdb_alt+akas" if from_tmdb else "akas"
            key = (hit["tconst"], "akas")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            pooled.append({**hit, "source": src, "query_norm": n})
        for hit in by_norm_basics.get(n, []):
            src = "tmdb_alt+basics" if from_tmdb else "basics"
            key = (hit["tconst"], "basics")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            pooled.append({**hit, "source": src, "query_norm": n})

    out: list[dict] = []
    by_tt: dict[str, dict] = {}
    for hit in pooled:
        tt = hit["tconst"]
        info = meta.get(tt)
        if not info:
            continue
        ok, delta = year_ok(info.get("startYear"), target.get("year"), YEAR_TOLERANCE)
        if not ok:
            continue
        # Prefer preferred types; keep video only if nothing else later
        sc, tie = score_candidate(hit, info, target.get("year"), delta)
        cand = {
            **hit,
            "titleType": info["titleType"],
            "primaryTitle": info["primaryTitle"],
            "originalTitle": info["originalTitle"],
            "startYear": info["startYear"],
            "genres": info["genres"],
            "is_horror": info["is_horror"],
            "year_delta": delta,
            "score": sc,
            "tie": tie,
        }
        prev = by_tt.get(tt)
        if prev is None or cand["tie"] < prev["tie"]:
            by_tt[tt] = cand

    out = list(by_tt.values())
    # Drop video if any preferred type remains
    preferred = [c for c in out if c["titleType"] in PREFERRED_TYPES]
    if preferred:
        out = preferred
    out.sort(key=lambda c: c["tie"])
    return out


def classify(target: dict, cands: list[dict]) -> dict:
    base = {
        "id": target["id"],
        "title": target["title"],
        "original_title": target["original_title"],
        "year": target["year"] if target["year"] is not None else "",
        "query_titles": "|".join(target.get("query_titles") or []),
        "candidates": cands,
        "source_list": target.get("source_list") or "",
    }
    if not cands:
        return {**base, "status": "none", "match_reason": "", "accepted": None}

    # Require year for auto-accept (unambiguous high confidence)
    if target.get("year") is None:
        if len(cands) == 1 and cands[0].get("is_horror"):
            return {
                **base,
                "status": "unique",
                "match_reason": "unique_no_year_horror",
                "accepted": cands[0],
            }
        return {**base, "status": "ambiguous", "match_reason": "no_year", "accepted": None}

    best = cands[0]
    # Unique tconst after year filter
    if len(cands) == 1:
        reason = "unique"
        if best.get("year_delta") == 1:
            reason = "unique_year_pm1"
        elif best.get("year_delta") == 2:
            reason = "unique_year_pm2"
        if best["source"].startswith("tmdb"):
            reason = f"tmdb_alt_{reason}"
        elif best["source"] == "akas":
            reason = f"akas_{reason}"
        elif best["source"] == "basics":
            reason = f"basics_{reason}"
        return {**base, "status": "unique", "match_reason": reason, "accepted": best}

    # Score gap: clear winner
    if len(cands) >= 2 and cands[0]["score"] >= cands[1]["score"] + 4:
        reason = "score_gap"
        if best["source"].startswith("tmdb"):
            reason = f"tmdb_alt_{reason}"
        elif best["source"] == "akas":
            reason = f"akas_{reason}"
        else:
            reason = f"basics_{reason}"
        return {**base, "status": "unique", "match_reason": reason, "accepted": best}

    horror_only = [c for c in cands if c.get("is_horror")]
    if len(horror_only) == 1:
        c = horror_only[0]
        reason = "horror_disambiguated"
        if c["source"].startswith("tmdb"):
            reason = f"tmdb_alt_{reason}"
        elif c["source"] == "akas":
            reason = f"akas_{reason}"
        else:
            reason = f"basics_{reason}"
        return {**base, "status": "unique", "match_reason": reason, "accepted": c}

    return {**base, "status": "ambiguous", "match_reason": "", "accepted": None}


def fetch_tmdb_alts(
    session: requests.Session,
    api_key: str,
    pid: int,
    delay: float,
) -> list[str]:
    url = ALT_URL.format(pid=pid)
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
            return []
        if r.status_code == 401:
            raise SystemExit("TMDB 401 — check TMDB_API_KEY")
        if not r.ok:
            time.sleep(1 + attempt)
            continue
        titles = []
        for item in r.json().get("titles") or []:
            t = (item.get("title") or "").strip()
            if t:
                titles.append(t)
        time.sleep(delay)
        return titles
    return []


def enrich_tmdb_alts(
    targets: list[dict],
    api_key: str,
    delay: float,
    cache_path: Path,
) -> None:
    cache: dict[str, list[str]] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}

    session = requests.Session()
    n = len(targets)
    fetched = 0
    for i, t in enumerate(targets, 1):
        pid = str(t["id"])
        if pid in cache:
            t["tmdb_alts"] = list(cache[pid])
            continue
        alts = fetch_tmdb_alts(session, api_key, t["id"], delay)
        cache[pid] = alts
        t["tmdb_alts"] = alts
        fetched += 1
        if i % 25 == 0 or i == n:
            print(f"  TMDB alts {i}/{n} (fetched this run: {fetched})")
            cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    n_with = sum(1 for t in targets if t.get("tmdb_alts"))
    print(f"  TMDB alternative_titles: {n_with:,}/{n:,} targets with ≥1 alt")


def build_query_titles(target: dict) -> list[str]:
    titles: list[str] = []
    for raw in (
        target.get("title"),
        target.get("original_title"),
        *(target.get("tmdb_alts") or []),
    ):
        s = (raw or "").strip()
        if s and s not in titles:
            titles.append(s)
    return titles


def source_bucket(match_reason: str, accepted: dict | None) -> str:
    if not accepted:
        return "none"
    src = accepted.get("source") or ""
    if src.startswith("tmdb_alt"):
        return "tmdb_alt"
    if src == "akas":
        return "akas"
    if src == "basics":
        return "basics"
    if match_reason.startswith("tmdb"):
        return "tmdb_alt"
    if match_reason.startswith("akas"):
        return "akas"
    if match_reason.startswith("basics"):
        return "basics"
    return src or "other"


def write_hits(rows: list[dict]) -> None:
    fields = [
        "id",
        "title",
        "original_title",
        "year",
        "tconst",
        "titleType",
        "primaryTitle",
        "matched_title",
        "startYear",
        "year_delta",
        "source",
        "region",
        "match_reason",
        "score",
        "query_titles",
    ]
    with HITS_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            c = r["accepted"]
            w.writerow(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "original_title": r["original_title"],
                    "year": r["year"],
                    "tconst": c["tconst"],
                    "titleType": c["titleType"],
                    "primaryTitle": c["primaryTitle"],
                    "matched_title": c.get("aka_title") or "",
                    "startYear": c["startYear"] if c["startYear"] is not None else "",
                    "year_delta": c["year_delta"] if c["year_delta"] is not None else "",
                    "source": c.get("source") or "",
                    "region": c.get("region") or "",
                    "match_reason": r["match_reason"],
                    "score": c.get("score") or "",
                    "query_titles": r.get("query_titles") or "",
                }
            )


def write_ambiguous(rows: list[dict]) -> None:
    fields = [
        "id",
        "title",
        "original_title",
        "year",
        "n_candidates",
        "tconsts",
        "primaryTitles",
        "startYears",
        "sources",
        "scores",
        "match_reason",
    ]
    with AMBIG_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            cs = r["candidates"][:12]
            w.writerow(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "original_title": r["original_title"],
                    "year": r["year"],
                    "n_candidates": len(r["candidates"]),
                    "tconsts": "|".join(c["tconst"] for c in cs),
                    "primaryTitles": "|".join(c["primaryTitle"] for c in cs),
                    "startYears": "|".join(
                        str(c["startYear"]) if c["startYear"] is not None else ""
                        for c in cs
                    ),
                    "sources": "|".join(c.get("source") or "" for c in cs),
                    "scores": "|".join(str(c.get("score") or "") for c in cs),
                    "match_reason": r.get("match_reason") or "",
                }
            )


def write_miss(rows: list[dict]) -> None:
    fields = ["id", "title", "original_title", "year", "query_titles", "source_list"]
    with MISS_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "original_title": r["original_title"],
                    "year": r["year"],
                    "query_titles": r.get("query_titles") or "",
                    "source_list": r.get("source_list") or "",
                }
            )


def apply_hits(hits: list[dict]) -> list[dict]:
    """Backup HM, merge unambiguous hits into sidecar + horror_movies."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if HM.exists() and not HM_BACKUP.exists():
        shutil.copy2(HM, HM_BACKUP)
        print(f"backup → {HM_BACKUP}")

    sidecar = load_sidecar()
    applied: list[dict] = []
    for r in hits:
        pid = int(r["id"])
        tt = r["accepted"]["tconst"]
        # only apply if still empty / invalid
        if valid_tt(sidecar.get(pid, "")):
            continue
        sidecar[pid] = tt
        applied.append(
            {
                "id": pid,
                "imdb_id": tt,
                "title": r["title"],
                "original_title": r["original_title"],
                "year": r["year"],
                "matched_title": r["accepted"].get("aka_title") or "",
                "primaryTitle": r["accepted"].get("primaryTitle") or "",
                "match_reason": r["match_reason"],
                "source": r["accepted"].get("source") or "",
            }
        )

    write_sidecar(sidecar)
    merge_into_horror_movies(sidecar)

    fields = [
        "id",
        "imdb_id",
        "title",
        "original_title",
        "year",
        "matched_title",
        "primaryTitle",
        "match_reason",
        "source",
    ]
    with APPLIED_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in applied:
            w.writerow(row)
    return applied


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="write reports; do not merge")
    ap.add_argument("--no-tmdb", action="store_true", help="skip TMDB alternative_titles")
    ap.add_argument(
        "--also-missing-features",
        action="store_true",
        help=f"also include ids from {MISSING_FEATURES.name}",
    )
    ap.add_argument(
        "--include-already-tt",
        action="store_true",
        help="do not skip rows that already have a valid tt in HM/sidecar",
    )
    ap.add_argument("--tmdb-delay", type=float, default=0.25)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--akas", type=Path, default=None)
    ap.add_argument("--basics", type=Path, default=None)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()

    targets = load_targets(
        also_missing_features=args.also_missing_features,
        limit=args.limit,
        include_already_tt=args.include_already_tt,
    )
    if not targets:
        print("no targets — nothing to do")
        return

    # Optional TMDB alts before indexing so one AKA/basics scan covers them
    api_key = ""
    if not args.no_tmdb:
        api_key = get_tmdb_key(args.api_key)
        if api_key:
            print("fetching TMDB alternative_titles …")
            enrich_tmdb_alts(targets, api_key, args.tmdb_delay, TMDB_CACHE)
        else:
            print("TMDB_API_KEY missing — continuing without alternative_titles")

    for t in targets:
        t["query_titles"] = build_query_titles(t)

    needed: set[str] = set()
    tmdb_norms: set[str] = set()
    all_raw: list[str] = []
    for t in targets:
        for raw in t["query_titles"]:
            all_raw.append(raw)
            n = normalize_title(raw)
            if n:
                needed.add(n)
        for raw in t.get("tmdb_alts") or []:
            n = normalize_title(raw)
            if n:
                tmdb_norms.add(n)
    print(f"unique normalized query keys: {len(needed):,}")

    akas_path = args.akas or AKAS_GZ
    basics_path = args.basics or BASICS_GZ
    if not akas_path.exists():
        raise SystemExit(f"missing {akas_path}")
    if not basics_path.exists():
        raise SystemExit(f"missing {basics_path}")

    aka_lookup = build_akas_lookup(all_raw, needed)
    print(f"AKA casefold lookup keys: {len(aka_lookup):,}")
    print(f"scanning akas {akas_path} …")
    by_norm_akas = scan_akas(akas_path, aka_lookup)
    aka_tconsts = {h["tconst"] for lst in by_norm_akas.values() for h in lst}
    print(f"AKA candidate tconsts: {len(aka_tconsts):,}")

    print(f"scanning basics {basics_path} …")
    by_norm_basics, meta = scan_basics(basics_path, needed, aka_tconsts)

    results = []
    for t in targets:
        cands = gather_candidates(
            t, by_norm_akas, by_norm_basics, meta, tmdb_norm_set=tmdb_norms
        )
        results.append(classify(t, cands))

    hits = [r for r in results if r["status"] == "unique" and r["accepted"]]
    ambig = [r for r in results if r["status"] == "ambiguous"]
    miss = [r for r in results if r["status"] == "none"]

    write_hits(hits)
    write_ambiguous(ambig)
    write_miss(miss)

    by_src = Counter(source_bucket(r["match_reason"], r["accepted"]) for r in hits)

    print()
    print("=== results ===")
    print(f"  misses in:     {len(targets):,}")
    print(f"  hits:          {len(hits):,}")
    for src, n in sorted(by_src.items()):
        print(f"    by source {src}: {n:,}")
    print(f"  ambiguous:     {len(ambig):,}")
    print(f"  still miss:    {len(miss):,}")
    print(f"  → {HITS_OUT}")
    print(f"  → {AMBIG_OUT}")
    print(f"  → {MISS_OUT}")

    # Sample: Love Me Dead / interesting AKA wins
    print("\nsample hits:")
    interesting = [
        r
        for r in hits
        if "love me dead" in (r.get("title") or "").casefold()
        or "love me dead" in (r.get("original_title") or "").casefold()
        or "love me dead" in (r.get("query_titles") or "").casefold()
        or "issac" in (r.get("title") or "").casefold()
        or "issac" in (r.get("original_title") or "").casefold()
        or (r["accepted"].get("source") or "").startswith("akas")
        or (r["accepted"].get("source") or "").startswith("tmdb")
    ]
    show = interesting[:8] if interesting else hits[:8]
    if not show and hits:
        show = hits[:8]
    for r in show[:12]:
        c = r["accepted"]
        print(
            f"  {r['id']:>8}  {(r['title'] or '')[:36]:<36}  "
            f"{r['year']} → {c['tconst']}  "
            f"[{c.get('source')}] matched={c.get('aka_title')!r}  "
            f"({r['match_reason']})"
        )

    applied: list[dict] = []
    if args.dry_run:
        print("\n(--dry-run: skipping HM / sidecar merge)")
    else:
        # Apply only unique year-anchored (or unique_no_year_horror) hits
        apply_ready = [
            r
            for r in hits
            if r["accepted"]
            and (
                r.get("year") != ""
                and r.get("year") is not None
                or r["match_reason"] == "unique_no_year_horror"
            )
        ]
        applied = apply_hits(apply_ready)
        print(f"\napplied {len(applied):,} → {SIDECAR.name} + {HM.name}")
        print(f"  → {APPLIED_OUT}")

    summary = {
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "n_misses_in": len(targets),
        "n_hits": len(hits),
        "n_hits_by_source": dict(by_src),
        "n_ambiguous": len(ambig),
        "n_still_miss": len(miss),
        "n_applied": len(applied),
        "dry_run": bool(args.dry_run),
        "used_tmdb": bool(api_key) and not args.no_tmdb,
        "year_tolerance": YEAR_TOLERANCE,
        "outputs": {
            "hits": str(HITS_OUT),
            "miss": str(MISS_OUT),
            "ambiguous": str(AMBIG_OUT),
            "applied": str(APPLIED_OUT),
        },
        "sample_hits": [
            {
                "id": r["id"],
                "title": r["title"],
                "original_title": r["original_title"],
                "tconst": r["accepted"]["tconst"],
                "matched_title": r["accepted"].get("aka_title"),
                "primaryTitle": r["accepted"].get("primaryTitle"),
                "source": r["accepted"].get("source"),
                "match_reason": r["match_reason"],
            }
            for r in show[:15]
        ],
    }
    SUMMARY_OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"  → {SUMMARY_OUT}")


if __name__ == "__main__":
    main()
