#!/usr/bin/env python3
"""Enrich posters with AWS Rekognition signals (labels, moderation, faces, colors).

Complements local CLIP / YuNet / palette — does not replace them. Per image:
  DetectLabels (+ Image Properties) + DetectModerationLabels + DetectFaces
≈ 3 Group-2 API calls (~$0.003/poster → ~$80 for 27.6k).

  python3 rekognition_enrich.py --ids 578,948 --merge-lookup
  python3 rekognition_enrich.py --sample 200
  python3 rekognition_enrich.py --live-lookup          # full corpus, resume
  python3 rekognition_enrich.py --ids-file data/qa/rekognition_missing_ids.txt \\
      --workers 10 --sidecar data/qa/rekognition_community_enrich.csv --merge-main

Requires: aws configure, boto3. Region: us-east-1.

Outputs: data/rekognition.csv (and optional sidecar for parallel/resume).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

DATA = Path(__file__).parent / "data"
OUT = DATA / "rekognition.csv"
POSTERS = DATA / "posters"
REGION = "us-east-1"
MAX_BYTES = 5_000_000

FIELDS = [
    "id",
    "year",
    "title",
    "rek_labels",
    "rek_top",
    "rek_top_conf",
    "rek_weapon",
    "rek_animal",
    "rek_person",
    "rek_water",
    "rek_fire",
    "rek_silhouette",
    "rek_n_boxes",
    "rek_bright",
    "rek_sharp",
    "rek_contrast",
    "rek_colors",
    "rek_mod",
    "rek_violence",
    "rek_mod_weapons",
    "rek_gore",
    "rek_n_faces",
    "rek_emotion",
    "rek_gender",
    "rek_age_lo",
    "rek_age_hi",
]

WEAPON = {
    "weapon", "blade", "knife", "dagger", "sword", "gun", "handgun", "rifle",
    "axe", "hatchet", "bow", "arrow", "spear", "mace", "chainsaw",
}
ANIMAL = {
    "animal", "shark", "fish", "sea life", "insect", "bird", "dog", "cat",
    "wolf", "bear", "snake", "spider", "bat", "crow", "raven", "great white shark",
}
PERSON = {"person", "human", "man", "woman", "boy", "girl", "adult", "child", "face", "baby"}
WATER = {"water", "ocean", "sea", "lake", "beach", "wave", "underwater"}
FIRE = {"fire", "flame", "smoke", "explosion"}
SILHOUETTE = {"silhouette"}

_print_lock = threading.Lock()
_write_lock = threading.Lock()
_rate_lock = threading.Lock()
_next_slot = 0.0


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def acquire(min_interval: float) -> None:
    global _next_slot
    if min_interval <= 0:
        return
    with _rate_lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + min_interval
        wait = slot - now
    if wait > 0:
        time.sleep(wait)


def _client(region: str = REGION):
    return boto3.client(
        "rekognition",
        region_name=region,
        config=Config(retries={"max_attempts": 8, "mode": "adaptive"}),
    )


def _flag(labels, vocab):
    best = 0.0
    for name, conf in labels:
        if name.lower() in vocab:
            best = max(best, conf)
    return round(best, 4)


def _mod_score(mods, *names):
    want = {n.lower() for n in names}
    best = 0.0
    for name, conf in mods:
        if name.lower() in want:
            best = max(best, conf)
    return round(best, 4)


def _image_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) <= MAX_BYTES:
        return data
    try:
        from poster_ocr_rek_text import prepare_bytes

        return prepare_bytes(path)
    except Exception as e:
        raise ValueError(f"image >5MB and shrink failed: {e}") from e


def _call_with_retries(fn, min_interval: float, attempts: int = 6):
    last = None
    for attempt in range(attempts):
        acquire(min_interval)
        try:
            return fn()
        except ClientError as e:
            last = e
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ThrottlingException", "ProvisionedThroughputExceededException"):
                time.sleep(min(20, 1.5 * (2**attempt)))
                continue
            raise
    raise last  # type: ignore[misc]


def analyze(client, path: Path, min_interval: float = 0.0) -> dict:
    data = _image_bytes(path)

    # 1) Labels + image properties
    lab = _call_with_retries(
        lambda: client.detect_labels(
            Image={"Bytes": data},
            MaxLabels=20,
            MinConfidence=50,
            Features=["GENERAL_LABELS", "IMAGE_PROPERTIES"],
            Settings={"ImageProperties": {"MaxDominantColors": 5}},
        ),
        min_interval,
    )
    labels = [(l["Name"], float(l["Confidence"]) / 100.0) for l in lab.get("Labels", [])]
    n_boxes = sum(len(l.get("Instances") or []) for l in lab.get("Labels", []))
    ip = lab.get("ImageProperties") or {}
    q = ip.get("Quality") or {}
    colors = ip.get("DominantColors") or []
    color_s = "|".join(
        f"{c.get('HexCode', '')}:{round(float(c.get('PixelPercent', 0)), 1)}"
        for c in colors[:5]
    )
    label_s = "|".join(f"{n}:{c:.2f}" for n, c in labels[:10])

    # 2) Moderation
    mod = _call_with_retries(
        lambda: client.detect_moderation_labels(Image={"Bytes": data}, MinConfidence=40),
        min_interval,
    )
    mods = [
        (m["Name"], float(m["Confidence"]) / 100.0)
        for m in mod.get("ModerationLabels", [])
    ]
    mod_s = "|".join(f"{n}:{c:.2f}" for n, c in mods[:8])

    # 3) Faces (often empty on painted posters — still useful on photo sheets)
    faces = _call_with_retries(
        lambda: client.detect_faces(Image={"Bytes": data}, Attributes=["ALL"]),
        min_interval,
    )
    details = faces.get("FaceDetails") or []
    emotion = gender = ""
    age_lo = age_hi = -1
    if details:
        # largest face by bounding box area
        details = sorted(
            details,
            key=lambda f: f["BoundingBox"]["Width"] * f["BoundingBox"]["Height"],
            reverse=True,
        )
        f0 = details[0]
        emos = sorted(f0.get("Emotions") or [], key=lambda e: -e["Confidence"])
        if emos:
            emotion = f"{emos[0]['Type']}:{emos[0]['Confidence']/100:.2f}"
        gender = (f0.get("Gender") or {}).get("Value") or ""
        ar = f0.get("AgeRange") or {}
        age_lo = int(ar.get("Low", -1))
        age_hi = int(ar.get("High", -1))

    top_n, top_c = (labels[0][0], labels[0][1]) if labels else ("", 0.0)
    return dict(
        rek_labels=label_s,
        rek_top=top_n,
        rek_top_conf=round(top_c, 4),
        rek_weapon=_flag(labels, WEAPON),
        rek_animal=_flag(labels, ANIMAL),
        rek_person=_flag(labels, PERSON),
        rek_water=_flag(labels, WATER),
        rek_fire=_flag(labels, FIRE),
        rek_silhouette=_flag(labels, SILHOUETTE),
        rek_n_boxes=int(n_boxes),
        rek_bright=round(float(q.get("Brightness") or 0), 2),
        rek_sharp=round(float(q.get("Sharpness") or 0), 2),
        rek_contrast=round(float(q.get("Contrast") or 0), 2),
        rek_colors=color_s,
        rek_mod=mod_s,
        rek_violence=_mod_score(mods, "Violence", "Graphic Violence"),
        rek_mod_weapons=_mod_score(mods, "Weapons"),
        rek_gore=_mod_score(
            mods, "Visually Disturbing", "Blood & Gore", "Gore",
            "Emaciated Bodies", "Corpses", "Hanging",
        ),
        rek_n_faces=len(details),
        rek_emotion=emotion,
        rek_gender=gender,
        rek_age_lo=age_lo,
        rek_age_hi=age_hi,
    )


def _as_float(val) -> float:
    try:
        return float(val)
    except Exception:
        return 0.0


def _year_int(val) -> int:
    try:
        y = int(float(val))
        return y if y > 0 else 0
    except Exception:
        return 0


def decade_summary(rows: dict[int, dict] | list[dict]) -> dict:
    """Share of posters with weapon/animal/violence flags by decade."""
    records = list(rows.values()) if isinstance(rows, dict) else list(rows)
    by_dec: dict[int, list[dict]] = {}
    for r in records:
        y = _year_int(r.get("year"))
        if y <= 0:
            continue
        by_dec.setdefault(y // 10 * 10, []).append(r)
    out = {}
    for dec, g in sorted(by_dec.items()):
        n = len(g)

        def mean_flag(key: str, thr: float) -> float:
            return round(sum(1 for r in g if _as_float(r.get(key)) > thr) / n, 4)

        out[str(int(dec))] = {
            "n": n,
            "weapon": mean_flag("rek_weapon", 0.5),
            "animal": mean_flag("rek_animal", 0.5),
            "person": mean_flag("rek_person", 0.5),
            "violence": mean_flag("rek_violence", 0.4),
            "gore": mean_flag("rek_gore", 0.4),
            "has_face": round(sum(1 for r in g if _as_float(r.get("rek_n_faces")) > 0) / n, 4),
            "silhouette": mean_flag("rek_silhouette", 0.5),
        }
    return out


def load_meta_map() -> dict[int, dict]:
    out: dict[int, dict] = {}
    sources = [
        DATA / "posters.csv",
        DATA / "community" / "community_manifest.csv",
        DATA / "horror_movies.csv",
    ]
    for path in sources:
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(float(r["id"]))
                except Exception:
                    continue
                cur = out.setdefault(pid, {})
                if r.get("title") and not cur.get("title"):
                    cur["title"] = r["title"]
                year = r.get("year") or ""
                if not year:
                    rd = (r.get("release_date") or "")[:4]
                    year = rd if rd.isdigit() else ""
                if year and not cur.get("year"):
                    cur["year"] = year
    return out


def load_ids_file(path: Path) -> list[int]:
    ids: list[int] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".csv" or (text.lstrip().startswith("id") and "," in text.split("\n", 1)[0]):
        with path.open(encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames and "id" in reader.fieldnames:
                for r in reader:
                    try:
                        ids.append(int(float(r["id"])))
                    except Exception:
                        pass
                return ids
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            ids.append(int(float(line.split(",")[0].strip())))
        except Exception:
            pass
    return ids


def load_csv_rows(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    out: dict[int, dict] = {}
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(float(r["id"]))
            except Exception:
                continue
            out[pid] = {k: r.get(k, "") for k in FIELDS}
    return out


def _write_csv_rows_unlocked(path: Path, rows: dict[int, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for pid in sorted(rows):
            w.writerow(rows[pid])
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def write_csv_rows(path: Path, rows: dict[int, dict]) -> None:
    with _write_lock:
        _write_csv_rows_unlocked(path, rows)


def merge_into_main(main_rows: dict[int, dict], new_rows: dict[int, dict]) -> None:
    """Merge under process lock + advisory file lock to avoid multi-writer corruption."""
    import fcntl

    main_rows.update(new_rows)
    lock_path = OUT.with_suffix(".csv.lock")
    with _write_lock:
        with lock_path.open("w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                # re-read disk under lock so we don't clobber other writers
                disk = load_csv_rows(OUT)
                disk.update(main_rows)
                main_rows.clear()
                main_rows.update(disk)
                _write_csv_rows_unlocked(OUT, main_rows)
                (DATA / "rekognition_decade.json").write_text(
                    json.dumps(decade_summary(main_rows), indent=2), encoding="utf-8"
                )
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--ids-file", default="", help="txt/csv of ids to process")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--min-interval", type=float, default=0.05,
                    help="min seconds between Rekognition API calls (shared)")
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--sidecar", default="",
                    help="checkpoint CSV (resume). Empty = write only to rekognition.csv")
    ap.add_argument("--merge-main", action="store_true",
                    help="periodically merge sidecar successes into rekognition.csv")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true",
                    help="reprocess even if already in sidecar/main")
    ap.add_argument("--live-lookup", action="store_true")
    ap.add_argument("--merge-lookup", action="store_true",
                    help="rebuild lookup.js at the end")
    args = ap.parse_args()

    meta_map = load_meta_map()
    want_ids: list[int] | None = None

    if args.ids_file:
        want_ids = load_ids_file(Path(args.ids_file))
    elif args.ids:
        want_ids = [int(x) for x in args.ids.split(",") if x.strip()]
    elif args.sample:
        import pandas as pd

        meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
        meta = meta.groupby(meta.year // 10 * 10, group_keys=False).apply(
            lambda g: g.sample(min(len(g), max(1, args.sample // 11)), random_state=42)
        )
        want_ids = [int(x) for x in meta.id.tolist()]
    else:
        # full posters.csv corpus (resume skips done)
        want_ids = []
        with (DATA / "posters.csv").open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    want_ids.append(int(float(r["id"])))
                except Exception:
                    pass

    if args.limit:
        want_ids = want_ids[: args.limit]

    sidecar = Path(args.sidecar) if args.sidecar else None
    main_rows = load_csv_rows(OUT)
    side_rows = load_csv_rows(sidecar) if sidecar else {}
    if sidecar and args.merge_main and side_rows:
        # ensure prior sidecar successes are already in main before resume
        pending = {k: v for k, v in side_rows.items() if k not in main_rows}
        if pending:
            merge_into_main(main_rows, pending)
            log(f"merged {len(pending)} prior sidecar rows into {OUT}")

    if args.force:
        done: set[int] = set()
    else:
        done = set(main_rows)
        if sidecar:
            # resume: skip successful sidecar rows even if not yet merged
            done |= set(side_rows)

    jobs = [pid for pid in want_ids if pid not in done and (POSTERS / f"{pid}.jpg").exists()]
    workers = max(1, args.workers)
    log(
        f"want={len(want_ids)} todo={len(jobs)} done_skip={len(want_ids)-len(jobs)} "
        f"workers={workers} sidecar={sidecar or '-'} merge_main={args.merge_main}"
    )
    if not jobs:
        log("nothing to do")
        return

    client = _client(args.region)
    t0 = time.time()
    ok = err = 0
    completed = 0
    new_ok: dict[int, dict] = {}

    def one(pid: int) -> dict | None:
        path = POSTERS / f"{pid}.jpg"
        m = meta_map.get(pid, {})
        try:
            feats = analyze(client, path, min_interval=args.min_interval)
        except Exception as e:
            log(f"fail {pid}: {type(e).__name__}: {e}")
            return None
        return dict(
            id=pid,
            year=_year_int(m.get("year")),
            title=str(m.get("title") or ""),
            **feats,
        )

    def checkpoint() -> None:
        if sidecar is not None:
            side_rows.update(new_ok)
            write_csv_rows(sidecar, side_rows)
            if args.merge_main and new_ok:
                merge_into_main(main_rows, new_ok)
        else:
            merge_into_main(main_rows, new_ok)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, pid): pid for pid in jobs}
        for fut in as_completed(futs):
            pid = futs[fut]
            row = fut.result()
            completed += 1
            if row is None:
                err += 1
            else:
                ok += 1
                new_ok[pid] = row
                if sidecar is not None:
                    side_rows[pid] = row
                else:
                    main_rows[pid] = row
            if completed % 10 == 0 or completed == len(jobs):
                rate = ok / max(time.time() - t0, 1e-6)
                title = (row or {}).get("title", "")[:26] if row else ""
                top = (row or {}).get("rek_top", "") if row else ""
                log(
                    f"[{completed}/{len(jobs)}] ok={ok} err={err} {rate:.2f}/s "
                    f"| {pid} {title!r} top={top!r}"
                )
            if ok and ok % args.save_every == 0:
                checkpoint()
                log(f"checkpoint ok={ok} → {sidecar or OUT}")

    checkpoint()
    elapsed = time.time() - t0
    rate = ok / max(elapsed, 1e-6)
    log(
        f"LISTO ok={ok} err={err} elapsed={elapsed/60:.1f}m ({rate:.2f}/s) "
        f"main={len(main_rows) if args.merge_main or sidecar is None else 'n/a'} "
        f"→ {sidecar or OUT}"
    )
    if args.merge_lookup or args.live_lookup:
        try:
            import build_lookup

            build_lookup.main()
        except Exception as e:
            log(f"lookup rebuild failed: {e}")


if __name__ == "__main__":
    main()
