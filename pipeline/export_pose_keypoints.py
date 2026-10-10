#!/usr/bin/env python3
"""Attach COCO-17 skeletons to pose.js when a source CSV still has keypoints.

The production pose_score.csv was scored with the compact schema
(n / spread / asym / conf only). A later ViTPose pass can persist box +
keypoints; until that full re-run, this also reads the 3k prodtest backup
that already stored geometry.

Coordinates in those CSVs are pixel space of the inference poster (TMDB
w500, width 500). This script normalizes to [0, 1] so the autopsy overlay
can draw a stick figure without knowing the original pixel size.

  python3 export_pose_keypoints.py
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SITE_DATA = HERE.parent / "site" / "data"
GLOBAL_SRC = DATA / "site_globals_full"
POSE_JS = GLOBAL_SRC / "pose.js"

BACKUP = DATA / "prodtest_3000_aws_backup" / "pose.csv"
SCORE = DATA / "qa" / "pose_score.csv"
KPTS = DATA / "qa" / "pose_kpts" / "pose_score_kpts.csv"
CATALOGS = [
    DATA / "multi_poster_catalog.csv",
    DATA / "multi_poster_catalog_scifi.csv",
    DATA / "multi_poster_catalog_thriller.csv",
    DATA / "multi_poster_catalog_mystery.csv",
]

INFER_W = 500.0  # YOLO person boxes in the backup never exceed x=500


def _js_payload(path: Path, marker: str = "window.POSE="):
    text = path.read_text(encoding="utf-8")
    start = text.index(marker) + len(marker)
    head = text[: text.index(marker)]
    return json.loads(text[start:].rstrip().rstrip(";")), head, marker


def _write_pose(path: Path, head: str, marker: str, data: dict) -> None:
    path.write_text(
        f"{head}{marker}{json.dumps(data, ensure_ascii=False, separators=(',', ':'))};\n",
        encoding="utf-8",
    )


def _w500_size(orig_w: int, orig_h: int) -> tuple[float, float]:
    if orig_w <= 0 or orig_h <= 0:
        return INFER_W, 750.0
    if orig_w >= 500:
        return INFER_W, round(orig_h * 500 / orig_w)
    return float(orig_w), float(orig_h)


def load_primary_sizes() -> dict[int, tuple[int, int]]:
    out: dict[int, tuple[int, int]] = {}
    for p in CATALOGS:
        if not p.exists():
            continue
        with p.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("is_primary", "") not in ("1", "True", "true", "TRUE"):
                    continue
                pid = r.get("id", "")
                if not pid.isdigit():
                    continue
                try:
                    w, h = int(float(r["width"])), int(float(r["height"]))
                except (KeyError, ValueError):
                    continue
                out[int(pid)] = (w, h)
    return out


def infer_hw(pid: int, box: list[float], sizes: dict[int, tuple[int, int]], row: dict | None = None) -> tuple[float, float]:
    if row:
        try:
            iw, ih = float(row.get("img_w") or 0), float(row.get("img_h") or 0)
            if iw > 0 and ih > 0:
                return iw, ih
        except (TypeError, ValueError):
            pass
    w, h = INFER_W, 750.0
    if pid in sizes:
        w, h = _w500_size(*sizes[pid])
    if box and len(box) == 4:
        # Person box is inside the inference image; never shrink below it.
        h = max(h, math.ceil(box[3]))
        w = max(w, math.ceil(box[2]) if box[2] > w else w)
    return float(w), float(h)


def parse_geom_row(r: dict) -> tuple[list[list[float]] | None, list[float] | None]:
    raw_k = (r.get("keypoints") or "").strip()
    raw_b = (r.get("box") or "").strip()
    if not raw_k.startswith("["):
        return None, None
    try:
        kpts = json.loads(raw_k)
        box = json.loads(raw_b) if raw_b.startswith("[") else None
    except json.JSONDecodeError:
        return None, None
    if not isinstance(kpts, list) or len(kpts) < 17:
        return None, None
    return kpts[:17], box if isinstance(box, list) and len(box) == 4 else None


def normalize(kpts: list, box: list | None, w: float, h: float) -> tuple[list, list | None]:
    nk = []
    for pt in kpts:
        x, y, s = float(pt[0]), float(pt[1]), float(pt[2])
        nk.append([round(x / w, 3), round(y / h, 3), round(s, 3)])
    nb = None
    if box:
        x0, y0, x1, y1 = (float(c) for c in box)
        nb = [
            round(x0 / w, 3),
            round(y0 / h, 3),
            round(max(0.0, (x1 - x0) / w), 3),
            round(max(0.0, (y1 - y0) / h), 3),
        ]
    if nb:
        vis = [p for p in nk if p[2] >= 0.45]
        if len(vis) >= 3:
            xs = sorted(p[0] for p in vis)
            ys = sorted(p[1] for p in vis)
            kcx, kcy = xs[len(xs) // 2], ys[len(ys) // 2]
            bx, by, bw, bh = nb
            if not (bx <= kcx <= bx + bw and by <= kcy <= by + bh):
                dx = bx + bw / 2 - kcx
                dy = by + bh / 2 - kcy
                nk = [[round(p[0] + dx, 3), round(p[1] + dy, 3), p[2]] for p in nk]
    return nk, nb


def _row_metrics(r: dict) -> list:
    n = r.get("n_persons") or r.get("n") or 0
    try:
        n = int(float(n))
    except (TypeError, ValueError):
        n = 0
    def f(key, *alts):
        for k in (key, *alts):
            v = r.get(k)
            if v not in (None, ""):
                try:
                    return round(float(v), 4)
                except (TypeError, ValueError):
                    return None
        return None
    return [
        n,
        f("kpt_bbox_area_frac", "spread"),
        f("limb_asymmetry", "asym"),
        f("mean_kpt_confidence", "conf"),
    ]


def load_geometry(sizes: dict[int, tuple[int, int]]) -> tuple[dict[int, tuple[list, list | None]], dict[int, list]]:
    """id -> skeleton; id -> [n, spread, asym, conf] for rows missing from pose.js."""
    geom: dict[int, tuple[list, list | None]] = {}
    metrics: dict[int, list] = {}
    shard_csvs = sorted((DATA / "qa" / "pose_kpts").glob("pose_score_kpts*.csv"))
    sources = [p for p in ([KPTS, *shard_csvs, SCORE, BACKUP]) if p.exists()]
    for src in sources:
        with src.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "keypoints" not in (reader.fieldnames or []):
                print(f"  skip {src.name}: no keypoints column")
                continue
            n_add = 0
            for r in reader:
                pid = r.get("id", "")
                if not pid.isdigit():
                    continue
                i = int(pid)
                if i not in metrics:
                    metrics[i] = _row_metrics(r)
                if i in geom:
                    continue
                kpts, box = parse_geom_row(r)
                if kpts is None:
                    continue
                w, h = infer_hw(i, box or [], sizes, r)
                geom[i] = normalize(kpts, box, w, h)
                n_add += 1
            print(f"  {src.name}: +{n_add:,} skeletons")
    return geom, metrics


def attach(row: list, geom: tuple[list, list | None]) -> list:
    kpts, box = geom
    base = list(row[:4])
    while len(base) < 4:
        base.append(None)
    base.append(kpts)
    base.append(box)
    return base


def main() -> int:
    if not POSE_JS.exists():
        raise SystemExit(f"falta {POSE_JS}")
    print("sizes...")
    sizes = load_primary_sizes()
    print(f"  primary posters: {len(sizes):,}")
    print("geometry...")
    geom, metrics = load_geometry(sizes)
    print(f"  unique skeletons: {len(geom):,}")

    data, head, marker = _js_payload(POSE_JS)
    n_hit = 0
    n_new = 0
    for k, row in data.items():
        if not k.isdigit() or not isinstance(row, list):
            continue
        g = geom.get(int(k))
        if not g:
            continue
        if not row or not row[0]:
            continue
        data[k] = attach(row, g)
        n_hit += 1
    for i, mets in metrics.items():
        k = str(i)
        if k in data:
            continue
        if not mets or not mets[0]:
            continue
        row = list(mets)
        g = geom.get(i)
        data[k] = attach(row, g) if g else row
        n_new += 1
    _write_pose(POSE_JS, head, marker, data)
    print(f"  globals_full pose.js: {n_hit:,} existing + {n_new:,} new rows with pose")

    from build_site import prune_id_global
    from corpus import canonical_ids

    prune_id_global("pose.js", canonical_ids())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
