#!/usr/bin/env python3
"""Sidecar of TMDB poster variants for autopsy.

Cluster representatives only (near-duplicates dropped). Does not change
which sheet the essay measured. Autopsy shows these as other faces of
the same film.

  python3 export_poster_alts.py

Writes site/data/poster_alts.json
  {id: [[file_path, iso, measured], ...]}  measured first, max 8
and site/data/poster_alts_rek.json
  {id: {file_path: [weapon, person, animal, fire, water, sil, bright, contrast]}}
  from qa/rekognition_multi_variants.csv — DetectLabels already run on variants.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE.parent / "site" / "data" / "poster_alts.json"
REK_SRC = DATA / "qa" / "rekognition_multi_variants.csv"
REK_OUT = HERE.parent / "site" / "data" / "poster_alts_rek.json"
REK_KEYS = (
    "rek_weapon",
    "rek_person",
    "rek_animal",
    "rek_fire",
    "rek_water",
    "rek_silhouette",
    "rek_bright",
    "rek_contrast",
)
MAX_ALTS = 8
CLUSTER_FILES = (
    DATA / "multi_poster_clusters.csv",
    DATA / "multi_poster_clusters_scifi.csv",
    DATA / "multi_poster_clusters_thriller.csv",
    DATA / "multi_poster_clusters_mystery.csv",
)


def _truthy(v: str) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes"}


def _tmdb_path(row: dict) -> str:
    raw = (row.get("file_path") or "").strip()
    if raw.startswith("/"):
        return raw
    name = Path(raw).name
    if name.endswith(".jpg"):
        return f"/{name}"
    stem = (row.get("stem") or "").replace(".jpg", "").strip()
    return f"/{stem}.jpg" if stem else ""


def _fnum(row: dict, key: str):
    try:
        return round(float(row[key]), 3)
    except (KeyError, TypeError, ValueError):
        return None


def write_rek(alts: dict[str, list]) -> None:
    wanted = {pid: {item[0] for item in rows if item} for pid, rows in alts.items()}
    out: dict[str, dict] = {}
    if not REK_SRC.is_file():
        print(f"skip rek sidecar: missing {REK_SRC}")
        return
    with REK_SRC.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("error"):
                continue
            try:
                pid = str(int(r["id"]))
            except (KeyError, TypeError, ValueError):
                continue
            paths = wanted.get(pid)
            if not paths:
                continue
            path = _tmdb_path(r)
            if path not in paths:
                continue
            out.setdefault(pid, {})[path] = [_fnum(r, k) for k in REK_KEYS]
    REK_OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n_paths = sum(len(v) for v in out.values())
    print(f"wrote {REK_OUT} films={len(out):,} paths={n_paths:,} bytes={REK_OUT.stat().st_size:,}")


def main() -> None:
    from corpus import canonical_ids

    keep = canonical_ids()
    measured: dict[int, str] = {}
    explorer = HERE.parent / "site" / "data" / "explorer.js"
    if explorer.is_file():
        text = explorer.read_text(encoding="utf-8")
        start = text.find("const POSTERS=")
        if start >= 0:
            start += len("const POSTERS=")
            end = text.rfind(";")
            rows = json.loads(text[start:end])
            for row in rows:
                try:
                    pid = int(row[7])
                    path = str(row[2] or "").strip()
                except (IndexError, TypeError, ValueError):
                    continue
                if pid in keep and path.startswith("/"):
                    measured[pid] = path

    # id → path → {iso, votes, measured}
    by_id: dict[int, dict[str, dict]] = {}
    for src in CLUSTER_FILES:
        if not src.is_file():
            continue
        with src.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if not _truthy(r.get("is_rep") or ""):
                    continue
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if pid not in keep:
                    continue
                path = (r.get("file_path") or "").strip()
                if not path.startswith("/"):
                    continue
                try:
                    votes = float(r.get("vote_count") or 0)
                except (TypeError, ValueError):
                    votes = 0
                iso = (r.get("iso_639_1") or "").strip().lower()
                slot = by_id.setdefault(pid, {})
                cur = slot.get(path)
                if cur is None or votes > cur["votes"]:
                    slot[path] = {"iso": iso, "votes": votes}

    out: dict[str, list] = {}
    for pid, paths in by_id.items():
        mine = measured.get(pid)
        if mine and mine not in paths:
            paths[mine] = {"iso": "", "votes": 10**9}
        if len(paths) < 2:
            continue
        rows = []
        for path, meta in paths.items():
            rows.append((path, meta["iso"], 1 if path == mine else 0, meta["votes"]))
        rows.sort(key=lambda x: (-x[2], -x[3]))
        rows = rows[:MAX_ALTS]
        out[str(pid)] = [[p, iso, m] for p, iso, m, _ in rows]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} films={len(out):,} bytes={OUT.stat().st_size:,}")
    write_rek(out)


if __name__ == "__main__":
    main()
