#!/usr/bin/env python3
"""Build site/data/explorer.js — light per-poster grid for the essay.

Schema per row (matches site/index.html):
  [year, dominantHex, poster_path|null, title, brightness, n_faces, creature, id]

  python3 build_explorer.py
"""
from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT.parent / "site" / "data" / "explorer.js"


def dominant_hex(palette) -> str:
    if not palette:
        return "#1a1a1c"
    s = str(palette).strip()
    try:
        pal = ast.literal_eval(s)
        if isinstance(pal, (list, tuple)) and pal:
            return str(pal[0])
    except (ValueError, SyntaxError):
        pass
    if s.startswith("#"):
        return s.split(",")[0].strip(" []'\"")
    return "#1a1a1c"


def main():
    paths: dict[int, str] = {}
    for src in (DATA / "horror_movies.csv", DATA / "poster_paths_backfill.csv"):
        if not src.exists():
            continue
        with src.open(newline="") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (TypeError, ValueError, KeyError):
                    continue
                p = r.get("poster_path") or ""
                if isinstance(p, str) and p.startswith("/"):
                    paths[pid] = p

    faces: dict[int, int] = {}
    with (DATA / "faces_v2.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            try:
                faces[int(r["id"])] = int(float(r["n_faces"]))
            except (TypeError, ValueError, KeyError):
                pass

    creatures: dict[int, str] = {}
    with (DATA / "census.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (TypeError, ValueError, KeyError):
                continue
            lab = (r.get("label") or "").strip()
            if lab:
                creatures[pid] = lab

    # Films with no art in our sources: keep marked off-site until art arrives.
    no_poster: set[int] = set()
    np_ids = DATA / "qa" / "no_poster" / "no_poster_ids.txt"
    if np_ids.is_file():
        no_poster = {
            int(x) for x in np_ids.read_text().split() if x.strip().isdigit()
        }

    from corpus import canonical_ids
    keep = canonical_ids()

    rows = []
    seen: set[int] = set()
    skipped_no_poster = 0
    with (DATA / "posters.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            pid = int(r["id"])
            if pid not in keep or pid in seen:
                continue
            seen.add(pid)
            if pid in no_poster:
                skipped_no_poster += 1
                continue
            rows.append([
                int(float(r["year"])),
                dominant_hex(r.get("palette")),
                paths.get(pid),
                r.get("title") or "",
                round(float(r["brightness"]), 1),
                faces.get(pid, 0),
                creatures.get(pid, ""),
                pid,
            ])

    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    note = f" (excluded no_poster={skipped_no_poster})" if skipped_no_poster else ""
    OUT.write_text(
        f"/* explorer grid n={len(rows)}{note} */\nconst POSTERS={payload};\n"
    )
    with_path = sum(1 for row in rows if row[2])
    print(
        f"escrito {OUT.relative_to(ROOT.parent)} "
        f"({len(rows):,} posters, {with_path:,} con poster_path"
        f"{', excluded no_poster=' + str(skipped_no_poster) if skipped_no_poster else ''})"
    )


if __name__ == "__main__":
    main()
