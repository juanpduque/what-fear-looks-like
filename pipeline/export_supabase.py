"""Upload the autopsy blobs in site/data/ to Supabase table poster_autopsy.

The essay keeps series.js, explorer.js and the world chart as static files.
This script sends the per-film records the autopsy used to download in bulk.

Requires the table from supabase/migrations/20261018120000_poster_autopsy.sql.

  export SUPABASE_URL=https://YOUR_PROJECT.supabase.co
  export SUPABASE_SERVICE_ROLE_KEY=...
  python3 export_supabase.py
  python3 export_supabase.py --dry-run
  python3 export_supabase.py --limit 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"

# (column, filename). JS files are `window.NAME = {...}`.
SOURCES = [
    ("lookup", "lookup.js"),
    ("pose", "pose.js"),
    ("creature_boxes", "creature_boxes.js"),
    ("weapon_boxes", "weapon_boxes.js"),
    ("saliency", "saliency.json"),
    ("title_ink", "title_ink.json"),
    ("omdb", "omdb.json"),
    ("medium_cl", "medium_cl.json"),
    ("key_art", "key_art.json"),
    ("alts", "poster_alts.json"),
    ("alts_rek", "poster_alts_rek.json"),
    ("alts_pose", "poster_alts_pose.json"),
    ("alts_sal", "poster_alts_sal.json"),
    ("alts_comp", "poster_alts_comp.json"),
    ("alts_faces", "poster_alts_faces.json"),
    ("alts_owl", "poster_alts_owl.json"),
    ("alts_text", "poster_alts_text.json"),
    ("alts_clip", "poster_alts_clip.json"),
]


def load_id_map(path: Path) -> dict:
    """Object keyed by film id, from a JSON file or a window.NAME assignment."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
    else:
        start = text.find("{")
        if start < 0:
            raise ValueError(f"{path} has no object")
        data = json.loads(text[start:].strip().rstrip(";"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not an object")
    return data


def rows_from_maps(maps: dict[str, dict], limit: int | None = None) -> list[dict]:
    ids: set[str] = set()
    for blob in maps.values():
        ids.update(blob)
    ordered = sorted((i for i in ids if str(i).isdigit()), key=int)
    if limit is not None:
        ordered = ordered[:limit]
    rows = []
    for film_id in ordered:
        row: dict = {"id": int(film_id)}
        for column, blob in maps.items():
            if film_id in blob:
                row[column] = blob[film_id]
        rows.append(row)
    return rows


def load_maps() -> dict[str, dict]:
    maps = {}
    for column, name in SOURCES:
        path = DATA / name
        if not path.exists():
            print(f"skip missing {path}", file=sys.stderr)
            continue
        maps[column] = load_id_map(path)
        print(f"{name}: {len(maps[column])} ids")
    return maps


def upload(rows: list[dict], url: str, key: str, batch: int) -> None:
    endpoint = url.rstrip("/") + "/rest/v1/poster_autopsy?on_conflict=id"
    for start in range(0, len(rows), batch):
        chunk = rows[start : start + batch]
        body = json.dumps(chunk, ensure_ascii=False, separators=(",", ":")).encode()
        req = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as res:
                res.read()
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:500]
            raise SystemExit(f"upload failed at row {start} ({err.code}): {detail}") from err
        print(f"upserted {start + len(chunk)}/{len(rows)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch", type=int, default=40)
    args = parser.parse_args()

    rows = rows_from_maps(load_maps(), args.limit)
    print(f"{len(rows)} films")
    if args.dry_run:
        return

    url = os.environ.get("SUPABASE_URL") or os.environ.get("VITE_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (service role, not the anon key)."
        )
    upload(rows, url, key, args.batch)


if __name__ == "__main__":
    main()
