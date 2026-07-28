#!/usr/bin/env python3
"""Compare TMDB horror corpus vs IMDb title.basics Horror titles.

Primary join key: imdb_id (tt…). Sources:
  TMDB  — horror_movies.csv / posters.csv + imdb_ids.csv
  IMDb  — data/imdb_datasets/title.basics.tsv.gz (genres contain Horror)

Writes under --out-dir (default data/qa/):
  tmdb_imdb_horror_matched.csv
  tmdb_imdb_horror_tmdb_no_tt.csv
  tmdb_imdb_horror_tmdb_tt_not_imdb_horror.csv
  tmdb_imdb_horror_imdb_only.csv
  tmdb_imdb_horror_summary.txt

Usage:
  python3 compare_tmdb_imdb_horror.py
  python3 compare_tmdb_imdb_horror.py --set posters
  python3 compare_tmdb_imdb_horror.py --set en --include-shorts
  python3 compare_tmdb_imdb_horror.py --set horror_movies --out-dir data/qa
"""
from __future__ import annotations

import argparse
import csv
import gzip
import sys
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
BASICS_GZ = DATA / "imdb_datasets" / "title.basics.tsv.gz"
HM = DATA / "horror_movies.csv"
SIDECAR = DATA / "imdb_ids.csv"
POSTERS = DATA / "posters.csv"
DEFAULT_QA = DATA / "qa"

STRICT_TYPES = frozenset({"movie", "tvMovie"})
EXTRA_TYPES = frozenset({"short", "video", "tvShort"})


def valid_tt(s: str | None) -> str | None:
    s = (s or "").strip()
    if s.startswith("tt") and len(s) > 2 and s[2:].isdigit():
        return s
    return None


def is_horror(genres: str) -> bool:
    if not genres or genres == "\\N":
        return False
    return "Horror" in genres.split(",")


def parse_int(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    if not raw or raw == "\\N":
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def load_tt_map() -> dict[int, str]:
    """Prefer imdb_ids.csv; fill gaps from horror_movies.imdb_id."""
    out: dict[int, str] = {}
    if SIDECAR.exists():
        with SIDECAR.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                tt = valid_tt(r.get("imdb_id"))
                if tt:
                    out[pid] = tt
    if HM.exists():
        with HM.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if pid in out:
                    continue
                tt = valid_tt(r.get("imdb_id"))
                if tt:
                    out[pid] = tt
    return out


def load_tmdb_set(kind: str) -> dict[int, dict]:
    """id → {title, year, original_language, runtime, genre_names}."""
    meta: dict[int, dict] = {}
    if not HM.exists():
        raise SystemExit(f"falta {HM}")

    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            year = parse_int(r.get("release_date", "")[:4] if r.get("release_date") else None)
            if year is None:
                year = parse_int(r.get("year"))
            meta[pid] = {
                "title": (r.get("title") or r.get("original_title") or "").strip(),
                "year": year,
                "original_language": (r.get("original_language") or "").strip(),
                "runtime": parse_int(r.get("runtime")),
                "genre_names": (r.get("genre_names") or "").strip(),
            }

    if kind == "horror_movies":
        return meta
    if kind == "en":
        return {pid: m for pid, m in meta.items() if m["original_language"] == "en"}
    if kind == "posters":
        if not POSTERS.exists():
            raise SystemExit(f"falta {POSTERS}")
        out: dict[int, dict] = {}
        with POSTERS.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                base = meta.get(pid, {})
                year = parse_int(r.get("year"))
                if year == 9999:
                    year = None
                out[pid] = {
                    "title": (r.get("title") or base.get("title") or "").strip(),
                    "year": year if year is not None else base.get("year"),
                    "original_language": base.get("original_language") or "",
                    "runtime": base.get("runtime"),
                    "genre_names": base.get("genre_names") or "",
                }
        return out
    raise SystemExit(f"set desconocido: {kind}")


def load_imdb_horror(basics: Path, include_shorts: bool) -> dict[str, dict]:
    """tconst → IMDb row for Horror titles in allowed titleTypes."""
    allowed = set(STRICT_TYPES)
    if include_shorts:
        allowed |= EXTRA_TYPES

    out: dict[str, dict] = {}
    n_rows = 0
    print(f"Escaneando {basics.name} (Horror + {sorted(allowed)})…")
    with gzip.open(basics, "rt", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            n_rows += 1
            if n_rows % 2_000_000 == 0:
                print(f"  … {n_rows:,} filas")
            ttype = row.get("titleType") or ""
            if ttype not in allowed:
                continue
            if not is_horror(row.get("genres") or ""):
                continue
            tt = row.get("tconst") or ""
            if not tt.startswith("tt"):
                continue
            out[tt] = {
                "imdb_id": tt,
                "titleType": ttype,
                "primaryTitle": row.get("primaryTitle") or "",
                "originalTitle": row.get("originalTitle") or "",
                "startYear": parse_int(row.get("startYear")),
                "runtimeMinutes": parse_int(row.get("runtimeMinutes")),
                "genres": row.get("genres") or "",
            }
    print(f"  {n_rows:,} filas → {len(out):,} Horror IMDb")
    return out


def lookup_tt_rows(basics: Path, need: set[str]) -> dict[str, dict]:
    """Fetch title.basics rows for specific tconsts (any type/genre)."""
    if not need:
        return {}
    found: dict[str, dict] = {}
    with gzip.open(basics, "rt", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            tt = row.get("tconst") or ""
            if tt not in need:
                continue
            found[tt] = {
                "imdb_id": tt,
                "titleType": row.get("titleType") or "",
                "primaryTitle": row.get("primaryTitle") or "",
                "originalTitle": row.get("originalTitle") or "",
                "startYear": parse_int(row.get("startYear")),
                "runtimeMinutes": parse_int(row.get("runtimeMinutes")),
                "genres": row.get("genres") or "",
                "is_horror": is_horror(row.get("genres") or ""),
            }
            if len(found) == len(need):
                break
    return found


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--set",
        choices=("posters", "en", "horror_movies"),
        default="posters",
        help="lado TMDB (default: posters = corpus analizado)",
    )
    ap.add_argument(
        "--include-shorts",
        action="store_true",
        help="en IMDb también contar short/video/tvShort con Horror",
    )
    ap.add_argument(
        "--basics",
        type=Path,
        default=BASICS_GZ,
        help="path a title.basics.tsv.gz",
    )
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_QA)
    args = ap.parse_args()

    if not args.basics.exists():
        raise SystemExit(f"falta {args.basics}")

    tmdb = load_tmdb_set(args.set)
    tt_map = load_tt_map()
    imdb = load_imdb_horror(args.basics, args.include_shorts)

    matched: list[dict] = []
    no_tt: list[dict] = []
    not_horror: list[dict] = []
    tmdb_tts: set[str] = set()
    tt_to_pids: dict[str, list[int]] = {}

    for pid, m in tmdb.items():
        tt = tt_map.get(pid)
        base = {
            "id": pid,
            "title": m.get("title") or "",
            "year": m.get("year") if m.get("year") is not None else "",
            "original_language": m.get("original_language") or "",
            "runtime": m.get("runtime") if m.get("runtime") is not None else "",
            "genre_names": m.get("genre_names") or "",
            "imdb_id": tt or "",
        }
        if not tt:
            no_tt.append(base)
            continue
        tmdb_tts.add(tt)
        tt_to_pids.setdefault(tt, []).append(pid)
        if tt in imdb:
            ib = imdb[tt]
            matched.append(
                {
                    **base,
                    "imdb_title": ib["primaryTitle"],
                    "imdb_year": ib["startYear"] if ib["startYear"] is not None else "",
                    "imdb_titleType": ib["titleType"],
                    "imdb_runtime": (
                        ib["runtimeMinutes"] if ib["runtimeMinutes"] is not None else ""
                    ),
                    "imdb_genres": ib["genres"],
                }
            )
        else:
            not_horror.append(base)

    # enrich not_horror with whatever title.basics says
    basics_hit = lookup_tt_rows(args.basics, {r["imdb_id"] for r in not_horror})
    type_counts: Counter[str] = Counter()
    horror_flag: Counter[str] = Counter()
    for r in not_horror:
        ib = basics_hit.get(r["imdb_id"])
        if not ib:
            r.update(
                {
                    "imdb_title": "",
                    "imdb_year": "",
                    "imdb_titleType": "",
                    "imdb_runtime": "",
                    "imdb_genres": "",
                    "reason": "tt_not_in_title_basics",
                }
            )
            type_counts["(missing)"] += 1
            horror_flag["missing"] += 1
            continue
        type_counts[ib["titleType"]] += 1
        horror_flag["horror" if ib["is_horror"] else "not_horror"] += 1
        reason = (
            "wrong_titleType"
            if ib["is_horror"]
            else "not_tagged_horror"
        )
        r.update(
            {
                "imdb_title": ib["primaryTitle"],
                "imdb_year": ib["startYear"] if ib["startYear"] is not None else "",
                "imdb_titleType": ib["titleType"],
                "imdb_runtime": (
                    ib["runtimeMinutes"] if ib["runtimeMinutes"] is not None else ""
                ),
                "imdb_genres": ib["genres"],
                "reason": reason,
            }
        )

    imdb_only: list[dict] = []
    for tt, ib in imdb.items():
        if tt in tmdb_tts:
            continue
        imdb_only.append(
            {
                "imdb_id": tt,
                "primaryTitle": ib["primaryTitle"],
                "originalTitle": ib["originalTitle"],
                "startYear": ib["startYear"] if ib["startYear"] is not None else "",
                "titleType": ib["titleType"],
                "runtimeMinutes": (
                    ib["runtimeMinutes"] if ib["runtimeMinutes"] is not None else ""
                ),
                "genres": ib["genres"],
            }
        )

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    prefix = "tmdb_imdb_horror"

    matched.sort(key=lambda r: (r.get("year") or 0, r["id"]))
    no_tt.sort(key=lambda r: (r.get("year") or 0, r["id"]))
    not_horror.sort(key=lambda r: (r.get("reason") or "", r.get("year") or 0, r["id"]))
    imdb_only.sort(
        key=lambda r: (r.get("startYear") or 0, r["imdb_id"]),
    )

    write_csv(
        out / f"{prefix}_matched.csv",
        matched,
        [
            "id",
            "title",
            "year",
            "original_language",
            "runtime",
            "genre_names",
            "imdb_id",
            "imdb_title",
            "imdb_year",
            "imdb_titleType",
            "imdb_runtime",
            "imdb_genres",
        ],
    )
    write_csv(
        out / f"{prefix}_tmdb_no_tt.csv",
        no_tt,
        [
            "id",
            "title",
            "year",
            "original_language",
            "runtime",
            "genre_names",
            "imdb_id",
        ],
    )
    write_csv(
        out / f"{prefix}_tmdb_tt_not_imdb_horror.csv",
        not_horror,
        [
            "id",
            "title",
            "year",
            "original_language",
            "runtime",
            "genre_names",
            "imdb_id",
            "imdb_title",
            "imdb_year",
            "imdb_titleType",
            "imdb_runtime",
            "imdb_genres",
            "reason",
        ],
    )
    write_csv(
        out / f"{prefix}_imdb_only.csv",
        imdb_only,
        [
            "imdb_id",
            "primaryTitle",
            "originalTitle",
            "startYear",
            "titleType",
            "runtimeMinutes",
            "genres",
        ],
    )

    n = len(tmdb)
    lines = [
        f"set={args.set}  include_shorts={args.include_shorts}",
        f"basics={args.basics}",
        f"TMDB n={n:,}",
        f"IMDb Horror n={len(imdb):,}",
        f"matched={len(matched):,} ({100 * len(matched) / max(n, 1):.1f}% TMDB)",
        f"tmdb_no_tt={len(no_tt):,}",
        f"tmdb_tt_not_imdb_horror={len(not_horror):,}",
        f"imdb_only={len(imdb_only):,}",
        "",
        "tmdb_tt_not_imdb_horror by titleType:",
        *[f"  {k}: {v:,}" for k, v in type_counts.most_common()],
        "tmdb_tt_not_imdb_horror horror flag:",
        *[f"  {k}: {v:,}" for k, v in horror_flag.most_common()],
        "",
        f"outputs → {out}/",
    ]
    summary = "\n".join(lines) + "\n"
    (out / f"{prefix}_summary.txt").write_text(summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
