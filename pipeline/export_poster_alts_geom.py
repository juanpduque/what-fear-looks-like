#!/usr/bin/env python3
"""Sidecars of alt-sheet YuNet / OWL / DetectText for autopsy peek.

Keyed by (id, file_path). Does not rewrite faces_v2, creature_boxes.js,
weapon_boxes.js, title_ink.json, or the measured cover.

  python3 export_poster_alts_geom.py

Writes:
  site/data/poster_alts_faces.json  {id: {path: [n, area, [[x,y,w,h], ...]]}}
  site/data/poster_alts_owl.json    {id: {path: {c:[{label,score,box}], w:[...]}}}
  site/data/poster_alts_text.json   {id: {path: [tx, tt, tw, th]}}

Alternate sheets often carry another release title ("The Trollenberg
Terror" for The Crawling Eye). When the catalog title is not found, lines are
matched strictly against Latin-script IMDb AKAs (data/imdb_datasets/
title.akas.tsv.gz via data/imdb_ids.csv); without those files it is skipped.
"""
from __future__ import annotations

import csv
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

from title_boxes_rekognition import aka_line_hits, title_line_hits

HERE = Path(__file__).resolve().parent
QA = HERE / "data" / "qa"
SITE_DATA = HERE.parent / "site" / "data"
ALTS_JSON = SITE_DATA / "poster_alts.json"
POSTERS = HERE / "data" / "posters.csv"
FACES_SRC = QA / "alts_yunet_catalog" / "pull" / "faces_alts.csv"
OWL_SRC = QA / "alts_owl_catalog" / "pull" / "owl_alts.csv"
TEXT_SRC = QA / "alts_text_catalog" / "pull" / "rekognition_text_boxes_alts.csv"
FACES_OUT = SITE_DATA / "poster_alts_faces.json"
OWL_OUT = SITE_DATA / "poster_alts_owl.json"
TEXT_OUT = SITE_DATA / "poster_alts_text.json"
IMDB_IDS = HERE / "data" / "imdb_ids.csv"
AKAS = HERE / "data" / "imdb_datasets" / "title.akas.tsv.gz"
MATCH_MIN = 0.72
LATIN = re.compile(r"[\x20-\x7E\u00C0-\u024F]+")


def tmdb_path(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("/") and raw.lower().endswith(".jpg"):
        return raw
    name = Path(raw).name
    return f"/{name}" if name.lower().endswith(".jpg") else ""


def parse_boxes(raw: str) -> list[list[float]]:
    if not raw or raw in {"nan", "[]"}:
        return []
    boxes = []
    for part in str(raw).split("|"):
        bits = part.split(",")
        if len(bits) != 4:
            continue
        try:
            boxes.append([round(float(b), 4) for b in bits])
        except ValueError:
            continue
    return boxes


def parse_owl(raw: str) -> list[dict]:
    if not raw or raw in {"nan", "[]"}:
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        box = r.get("box")
        if not isinstance(box, list) or len(box) != 4:
            continue
        try:
            xywh = [round(float(x), 4) for x in box]
            score = round(float(r.get("score") or 0), 3)
        except (TypeError, ValueError):
            continue
        lab = str(r.get("label") or "").strip()
        if not lab:
            continue
        out.append({"label": lab, "score": score, "box": xywh})
    return out


def union_box(boxes: list[tuple[float, float, float, float]]):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def wanted_alts() -> dict[str, set[str]]:
    if not ALTS_JSON.is_file():
        raise SystemExit(f"missing {ALTS_JSON}")
    data = json.loads(ALTS_JSON.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for pid, rows in data.items():
        paths = {str(item[0]) for item in rows if isinstance(item, list) and item and item[2] != 1}
        if paths:
            out[str(pid)] = paths
    return out


def load_titles(keep: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not POSTERS.is_file():
        return out
    with POSTERS.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            pid = (r.get("id") or "").strip()
            if pid not in keep:
                continue
            title = (r.get("title") or "").strip()
            if title:
                out[pid] = title
    return out


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n_paths = sum(len(v) for v in data.values())
    print(f"wrote {path} films={len(data):,} paths={n_paths:,} bytes={path.stat().st_size:,}")


def write_faces(wanted: dict[str, set[str]]) -> None:
    out: dict[str, dict] = {}
    if not FACES_SRC.is_file():
        print(f"skip faces sidecar: missing {FACES_SRC}")
        return
    with FACES_SRC.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "") != "ok":
                continue
            pid = (r.get("id") or "").strip()
            paths = wanted.get(pid)
            if not paths:
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if fp not in paths:
                continue
            try:
                n = int(float(r.get("n_faces") or 0))
            except (TypeError, ValueError):
                n = 0
            try:
                area = round(float(r.get("face_area") or 0), 4)
            except (TypeError, ValueError):
                area = 0.0
            out.setdefault(pid, {})[fp] = [n, area, parse_boxes(r.get("face_boxes") or "")]
    dump(FACES_OUT, out)


def write_owl(wanted: dict[str, set[str]]) -> None:
    out: dict[str, dict] = {}
    if not OWL_SRC.is_file():
        print(f"skip owl sidecar: missing {OWL_SRC}")
        return
    with OWL_SRC.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "") != "ok":
                continue
            pid = (r.get("id") or "").strip()
            paths = wanted.get(pid)
            if not paths:
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if fp not in paths:
                continue
            out.setdefault(pid, {})[fp] = {
                "c": parse_owl(r.get("creature_boxes") or ""),
                "w": parse_owl(r.get("weapon_boxes") or ""),
            }
    dump(OWL_OUT, out)


def load_akas(keep: set[str]) -> dict[str, set[str]]:
    """Latin-script IMDb AKAs per TMDB id (one streaming pass over the dump)."""
    if not (IMDB_IDS.is_file() and AKAS.is_file()):
        print(f"skip AKAs: missing {IMDB_IDS.name} or {AKAS}")
        return {}
    by_imdb: dict[str, str] = {}
    with IMDB_IDS.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("id") in keep and r.get("imdb_id"):
                by_imdb[r["imdb_id"]] = r["id"]
    out: dict[str, set[str]] = defaultdict(set)
    with gzip.open(AKAS, "rt", encoding="utf-8") as f:
        next(f)
        for line in f:
            tconst, _, aka = line.split("\t", 3)[:3]
            pid = by_imdb.get(tconst)
            if pid and LATIN.fullmatch(aka):
                out[pid].add(aka)
    return out


def write_text(wanted: dict[str, set[str]]) -> None:
    out: dict[str, dict] = {}
    if not TEXT_SRC.is_file():
        print(f"skip text sidecar: missing {TEXT_SRC}")
        return
    titles = load_titles(set(wanted))
    akas = load_akas(set(wanted))
    via_aka = 0
    with TEXT_SRC.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "") != "ok":
                continue
            pid = (r.get("id") or "").strip()
            paths = wanted.get(pid)
            if not paths:
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if fp not in paths:
                continue
            raw = r.get("lines") or ""
            try:
                lines = json.loads(raw) if raw and raw not in {"nan", "[]"} else []
            except json.JSONDecodeError:
                lines = []
            if not isinstance(lines, list):
                continue
            title = titles.get(pid) or ""
            if not title:
                continue
            boxes = [b for _, b, _ in title_line_hits(lines, title, MATCH_MIN)]
            if not boxes and akas.get(pid):
                boxes = [b for _, b, _ in aka_line_hits(lines, akas[pid] - {title})]
                via_aka += bool(boxes)
            if not boxes:
                continue
            ink = union_box(boxes)
            if ink[2] <= 0 or ink[3] <= 0:
                continue
            out.setdefault(pid, {})[fp] = ink
    print(f"text boxes via IMDb AKA: {via_aka:,}")
    dump(TEXT_OUT, out)


def main() -> None:
    wanted = wanted_alts()
    print(f"peek alts films={len(wanted):,} paths={sum(len(v) for v in wanted.values()):,}")
    write_faces(wanted)
    write_owl(wanted)
    write_text(wanted)


if __name__ == "__main__":
    main()
