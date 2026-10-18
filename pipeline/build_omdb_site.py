"""Compact OMDb card for the autopsy: site/data/omdb.json.

Reads the local, git-ignored pipeline/audit_omdb/results/omdb_all.jsonl (raw OMDb responses) and
keeps, for corpus films OMDb knows, only what the autopsy shows:
  {tmdb_id: [minutes|null, is_short 0/1, rated|"", countries, languages, director, cast, released]}
countries/languages keep the first two, cast the first three. is_short = OMDb genre "Short" or
runtime under 40 minutes. OMDb content is CC BY-NC 4.0; the page credits OMDb.

  python3 build_omdb_site.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "audit_omdb" / "results" / "omdb_all.jsonl"
CANON = HERE / "data" / "canonical_ids.txt"
OUT = HERE.parent / "site" / "data" / "omdb.json"
SHORT_MINUTES = 40


def clean(v):
    return None if v in (None, "", "N/A") else v


def head(v, n: int) -> str:
    v = clean(v)
    return ", ".join(x.strip() for x in v.split(",")[:n]) if v else ""


def card(o: dict) -> list:
    m = re.match(r"(\d+)", o.get("Runtime") or "")
    minutes = int(m.group(1)) if m else None
    genres = [g.strip() for g in (o.get("Genre") or "").split(",")]
    short = int("Short" in genres or (minutes is not None and minutes < SHORT_MINUTES))
    rated = clean(o.get("Rated")) or ""
    rated = "" if rated in ("Not Rated", "NOT RATED", "Unrated", "UNRATED") else rated
    return [
        minutes,
        short,
        rated,
        head(o.get("Country"), 2),
        head(o.get("Language"), 2),
        head(o.get("Director"), 2),
        head(o.get("Actors"), 3),
        clean(o.get("Released")) or "",
    ]


def main() -> None:
    canon = set(map(int, CANON.read_text().split()))
    out = {}
    for line in SRC.read_text().splitlines():
        rec = json.loads(line)
        o = rec["r"]
        if rec["id"] in canon and o.get("Response") == "True":
            out[rec["id"]] = card(o)
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(
        f"escrito {OUT.relative_to(HERE.parent)}: {len(out):,} películas, {OUT.stat().st_size / 1e6:.1f} MB"
    )


if __name__ == "__main__":
    main()
