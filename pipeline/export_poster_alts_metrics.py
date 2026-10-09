#!/usr/bin/env python3
"""Sidecars of alt-sheet pose / MSI-Net / composition for autopsy peek.

Keyed by (id, file_path). Does not rewrite pose.js, saliency.json, attributes.csv,
or measured maps/{id}.png.

  python3 export_poster_alts_metrics.py
  python3 export_poster_alts_metrics.py --from-s3
  python3 export_poster_alts_metrics.py --maps

Writes:
  pipeline/data/qa/pose_alts.csv
  pipeline/data/qa/saliency_alts.csv
  site/data/poster_alts_pose.json   {id: {path: [n, spread, asym, conf, kpts, box]}}
  site/data/poster_alts_sal.json    {id: {path: [peak_x, peak_y, mean]}}
  site/data/poster_alts_comp.json   {id: {path: {sym,neg,cx,mx,my,...}}}
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
QA = DATA / "qa"
SITE_DATA = HERE.parent / "site" / "data"
ALTS_JSON = SITE_DATA / "poster_alts.json"
POSE_MERGED = QA / "pose_alts.csv"
SAL_MERGED = QA / "saliency_alts.csv"
ATTR_SRC = QA / "attributes_multi_variants.csv"
POSE_OUT = SITE_DATA / "poster_alts_pose.json"
SAL_OUT = SITE_DATA / "poster_alts_sal.json"
COMP_OUT = SITE_DATA / "poster_alts_comp.json"
MAPS_DIR = QA / "saliency_alts" / "maps"
BUCKET = "wflike-workshop-posters-633183588025"
POSE_SHARDS = 12
MSINET_SHARDS = 8

COMP_KEYS = (
    ("symmetry", "sym"),
    ("neg_space", "neg"),
    ("complexity", "cx"),
    ("mass_x", "mx"),
    ("mass_y", "my"),
    ("text_area", "txt"),
    ("text_y", "ty"),
    ("align_score", "align"),
    ("thirds_dist", "thirds"),
    ("balance", "bal"),
    ("harmony", "harm"),
    ("diagonal_score", "diag"),
    ("pyramid_shift", "pyr"),
)


def tmdb_path(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("/") and raw.lower().endswith(".jpg"):
        return raw
    name = Path(raw).name
    return f"/{name}" if name.lower().endswith(".jpg") else ""


def tmdb_hash(file_path: str) -> str:
    name = Path(str(file_path or "").lstrip("/")).name
    return name[:-4] if name.lower().endswith(".jpg") else name


def _f(row: dict, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            try:
                return round(float(v), 4)
            except (TypeError, ValueError):
                return None
    return None


def _aws(args: list[str]) -> subprocess.CompletedProcess:
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(k, None)
    env.setdefault("AWS_PROFILE", "sandbox_bedrock")
    env.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    return subprocess.run(["aws", *args], env=env, capture_output=True, text=True)


def pull_shards() -> None:
    pose_dir = QA / "alts_pose_catalog" / "shards"
    sal_dir = QA / "alts_msinet_catalog" / "shards"
    pose_dir.mkdir(parents=True, exist_ok=True)
    sal_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for i in range(POSE_SHARDS):
        jobs.append(
            (
                f"s3://{BUCKET}/wflike-alts-pose-shard{i}/results/pose_alts.csv",
                pose_dir / f"pose_alts_{i}.csv",
            )
        )
    for i in range(MSINET_SHARDS):
        jobs.append(
            (
                f"s3://{BUCKET}/wflike-alts-msinet-shard{i}/results/saliency_alts.csv",
                sal_dir / f"saliency_alts_{i}.csv",
            )
        )

    def cp(src: str, dest: Path) -> str:
        r = _aws(["s3", "cp", src, str(dest)])
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-300:] or r.stdout[-300:] or src)
        return dest.name

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(cp, src, dest) for src, dest in jobs]
        for fut in as_completed(futs):
            print(f"  pulled {fut.result()}", flush=True)


def merge_csvs(pattern: str, dest: Path, key_fields: tuple[str, ...] = ("id", "file_path")) -> int:
    files = sorted(Path(p) for p in __import__("glob").glob(pattern))
    if not files:
        raise SystemExit(f"no shards matching {pattern}")
    rows: dict[tuple[str, str], dict] = {}
    fields: list[str] | None = None
    for src in files:
        with src.open(encoding="utf-8", newline="") as f:
            rd = csv.DictReader(f)
            if fields is None:
                fields = rd.fieldnames or []
            for r in rd:
                fp = tmdb_path(r.get("file_path") or "")
                pid = (r.get("id") or "").strip()
                if not pid or not fp:
                    continue
                r["file_path"] = fp
                prev = rows.get((pid, fp))
                if prev is None or (r.get("status") or "") == "ok":
                    rows[(pid, fp)] = r
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fields or [], extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows.values())
    print(f"merged {dest} rows={len(rows):,} from {len(files)} shards")
    return len(rows)


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


def normalize_pose(r: dict) -> list | None:
    if (r.get("status") or "") not in {"ok", ""}:
        return None
    try:
        n = int(float(r.get("n_persons") or 0))
    except (TypeError, ValueError):
        n = 0
    spread = _f(r, "kpt_bbox_area_frac")
    asym = _f(r, "limb_asymmetry")
    conf = _f(r, "mean_kpt_confidence")
    try:
        iw, ih = float(r.get("img_w") or 0), float(r.get("img_h") or 0)
    except (TypeError, ValueError):
        iw = ih = 0
    kpts = None
    box = None
    raw_k = (r.get("keypoints") or "").strip()
    raw_b = (r.get("box") or "").strip()
    if raw_k.startswith("["):
        try:
            kpts = json.loads(raw_k)
        except json.JSONDecodeError:
            kpts = None
    if raw_b.startswith("["):
        try:
            box = json.loads(raw_b)
        except json.JSONDecodeError:
            box = None
    nk = None
    nb = None
    if isinstance(kpts, list) and len(kpts) >= 17 and iw > 0 and ih > 0:
        nk = []
        for pt in kpts[:17]:
            if not isinstance(pt, list) or len(pt) < 3:
                continue
            nk.append([round(float(pt[0]) / iw, 3), round(float(pt[1]) / ih, 3), round(float(pt[2]), 3)])
        if len(nk) < 17:
            nk = None
    if isinstance(box, list) and len(box) == 4 and iw > 0 and ih > 0:
        x0, y0, x1, y1 = (float(c) for c in box)
        nb = [
            round(x0 / iw, 3),
            round(y0 / ih, 3),
            round(max(0.0, (x1 - x0) / iw), 3),
            round(max(0.0, (y1 - y0) / ih), 3),
        ]
    return [n, spread, asym, conf, nk, nb]


def write_pose(wanted: dict[str, set[str]]) -> None:
    out: dict[str, dict] = {}
    if not POSE_MERGED.is_file():
        print(f"skip pose sidecar: missing {POSE_MERGED}")
        return
    with POSE_MERGED.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            pid = (r.get("id") or "").strip()
            paths = wanted.get(pid)
            if not paths:
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if fp not in paths:
                continue
            row = normalize_pose(r)
            if row is None:
                continue
            out.setdefault(pid, {})[fp] = row
    POSE_OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {POSE_OUT} films={len(out):,} paths={sum(len(v) for v in out.values()):,} bytes={POSE_OUT.stat().st_size:,}")


def write_sal(wanted: dict[str, set[str]]) -> None:
    out: dict[str, dict] = {}
    if not SAL_MERGED.is_file():
        print(f"skip sal sidecar: missing {SAL_MERGED}")
        return
    with SAL_MERGED.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "") not in {"ok", ""}:
                continue
            pid = (r.get("id") or "").strip()
            paths = wanted.get(pid)
            if not paths:
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if fp not in paths:
                continue
            x, y, m = _f(r, "peak_x"), _f(r, "peak_y"), _f(r, "mean_saliency")
            if x is None or y is None:
                continue
            out.setdefault(pid, {})[fp] = [x, y, m]
    SAL_OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {SAL_OUT} films={len(out):,} paths={sum(len(v) for v in out.values()):,} bytes={SAL_OUT.stat().st_size:,}")


def write_comp(wanted: dict[str, set[str]]) -> None:
    out: dict[str, dict] = {}
    if not ATTR_SRC.is_file():
        print(f"skip comp sidecar: missing {ATTR_SRC}")
        return
    with ATTR_SRC.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "") not in {"ok", ""}:
                continue
            pid = (r.get("id") or "").strip()
            paths = wanted.get(pid)
            if not paths:
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if fp not in paths:
                continue
            rec = {dst: _f(r, src) for src, dst in COMP_KEYS}
            if all(v is None for v in rec.values()):
                continue
            out.setdefault(pid, {})[fp] = rec
    COMP_OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {COMP_OUT} films={len(out):,} paths={sum(len(v) for v in out.values()):,} bytes={COMP_OUT.stat().st_size:,}")


def pull_maps(_wanted: dict[str, set[str]] | None = None) -> None:
    """Sync shard map folders. Names are {id}_{stem}.png — never {id}.png."""
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"sync maps → {MAPS_DIR}", flush=True)

    def sync(i: int) -> str:
        src = f"s3://{BUCKET}/wflike-alts-msinet-shard{i}/results/maps/"
        r = _aws(["s3", "sync", src, str(MAPS_DIR)])
        if r.returncode != 0:
            return f"shard{i} FAIL {(r.stderr or r.stdout)[-200:]}"
        return f"shard{i} ok"

    with ThreadPoolExecutor(max_workers=8) as ex:
        for msg in ex.map(sync, range(MSINET_SHARDS)):
            print(f"  {msg}", flush=True)
    n = sum(1 for _ in MAPS_DIR.glob("*.png"))
    print(f"maps dir n={n:,} {MAPS_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-s3", action="store_true", help="download shard CSVs from the workshop bucket")
    ap.add_argument("--maps", action="store_true", help="download MSI-Net maps for poster_alts peek paths")
    ap.add_argument("--skip-merge", action="store_true")
    args = ap.parse_args()
    if args.from_s3:
        pull_shards()
    if not args.skip_merge:
        merge_csvs(str(QA / "alts_pose_catalog" / "shards" / "pose_alts_*.csv"), POSE_MERGED)
        merge_csvs(str(QA / "alts_msinet_catalog" / "shards" / "saliency_alts_*.csv"), SAL_MERGED)
    wanted = wanted_alts()
    print(f"peek alts films={len(wanted):,} paths={sum(len(v) for v in wanted.values()):,}")
    write_pose(wanted)
    write_sal(wanted)
    write_comp(wanted)
    if args.maps:
        pull_maps(wanted)


if __name__ == "__main__":
    main()
