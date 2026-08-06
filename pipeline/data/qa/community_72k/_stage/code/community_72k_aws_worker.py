#!/usr/bin/env python3
"""Community 72k AWS worker: download posters → S3, then Rekognition from S3Object.

Phases (resume-safe via S3 checkpoints):
  1) enumerate  — run tmdb_enumerate_horror if ids CSV missing on S3/local
  2) download   — TMDB CDN → s3://BUCKET/PREFIX/posters/{id}.jpg (skip existing)
  3) labels     — DetectLabels+IP + Moderation + Faces → results/rekognition_community_72k.csv
  4) detecttext — DetectText → results/detecttext_community_72k.csv

Skip ids already done (staged skip lists or prior result CSVs). Does NOT pull posters
to the Mac — EC2 writes directly to S3.

  python3 community_72k_aws_worker.py --phase all
  python3 community_72k_aws_worker.py --phase download --workers 24
  python3 community_72k_aws_worker.py --phase labels --workers 10
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
import requests
from botocore.config import Config
from botocore.exceptions import ClientError

BUCKET = os.environ.get("BUCKET", "sagemaker-studio-a5572760")
PREFIX = os.environ.get("PREFIX", "wflike-community-72k")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
IMG_BASE = os.environ.get("TMDB_IMG_BASE", "https://image.tmdb.org/t/p/original")
HEADERS = {"User-Agent": "PulpAnalytics-WhatFearLooksLike/1.0-community-72k"}

WORK = Path(os.environ.get("WORK_DIR", "/home/ubuntu/aof/pipeline"))
DATA = WORK / "data"
QA = DATA / "qa" / "community_72k"
LOCAL_IDS = QA / "tmdb_horror_ids.csv"
PROGRESS = QA / "PROGRESS.json"

LABEL_FIELDS = [
    "id", "year", "title",
    "rek_labels", "rek_top", "rek_top_conf",
    "rek_weapon", "rek_animal", "rek_person", "rek_water", "rek_fire", "rek_silhouette",
    "rek_n_boxes", "rek_bright", "rek_sharp", "rek_contrast", "rek_colors",
    "rek_mod", "rek_violence", "rek_mod_weapons", "rek_gore",
    "rek_n_faces", "rek_emotion", "rek_gender", "rek_age_lo", "rek_age_hi",
    "error",
]
TEXT_FIELDS = ["id", "full_ocr", "n_lines", "n_words", "mean_conf", "latency_s", "error"]

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
_thread_local = threading.local()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def s3():
    return boto3.client("s3", region_name=REGION, config=Config(retries={"max_attempts": 8, "mode": "adaptive"}))


def rek():
    return boto3.client(
        "rekognition",
        region_name=REGION,
        config=Config(retries={"max_attempts": 8, "mode": "adaptive"}),
    )


def session() -> requests.Session:
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        _thread_local.session = s
    return s


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


def s3_key(*parts: str) -> str:
    return "/".join([PREFIX.rstrip("/"), *[p.strip("/") for p in parts if p]])


def write_progress(doc: dict) -> None:
    QA.mkdir(parents=True, exist_ok=True)
    doc = {**doc, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "bucket": BUCKET, "prefix": PREFIX}
    PROGRESS.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    try:
        s3().upload_file(str(PROGRESS), BUCKET, s3_key("results", "PROGRESS.json"))
    except Exception as e:
        log(f"progress upload warn: {e}")


def load_ids_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                r["id"] = int(float(r["id"]))
            except Exception:
                continue
            rows.append(r)
    return rows


def load_id_set_file(path: Path) -> set[int]:
    out: set[int] = set()
    if not path.exists():
        return out
    text = path.read_text(encoding="utf-8", errors="replace")
    first = text.split("\n", 1)[0] if text else ""
    if "id" in first.lower() and "," in first:
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    out.add(int(float(r["id"])))
                except Exception:
                    pass
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.add(int(float(line.split(",")[0].strip())))
        except Exception:
            pass
    return out


def s3_object_exists(key: str) -> bool:
    try:
        s3().head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError:
        return False


def wait_if_pause_labels(poll_secs: float = 30.0) -> None:
    """Block Labels while results/PAUSE_LABELS (or input/qa/PAUSE_LABELS) exists on S3.

    Non-destructive gate for overlap with local rekognition_enrich: upload PAUSE, refresh
    skip_labels, then delete PAUSE to resume.
    """
    keys = [s3_key("results", "PAUSE_LABELS"), s3_key("input", "qa", "PAUSE_LABELS")]
    announced = False
    while True:
        hit = next((k for k in keys if s3_object_exists(k)), None)
        if not hit:
            if announced:
                log("PAUSE_LABELS cleared — continuing to labels")
                write_progress({"phase": "labels", "status": "pause_cleared"})
            return
        if not announced:
            log(f"PAUSE_LABELS present (s3://{BUCKET}/{hit}) — waiting before labels")
            write_progress({"phase": "labels", "status": "paused", "pause_key": hit})
            announced = True
        time.sleep(max(5.0, poll_secs))


def refresh_skip_from_s3(local_path: Path, *extra_paths: Path) -> set[int]:
    """Re-download skip_labels from S3 immediately before Labels (skip is frozen at chain start otherwise)."""
    key = s3_key("input", "qa", "skip_labels_ids.txt")
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        s3().download_file(BUCKET, key, str(local_path))
        log(f"refreshed skip_labels from s3://{BUCKET}/{key}")
    except Exception as e:
        log(f"skip_labels refresh warn: {e}")
    skip = load_id_set_file(local_path)
    for p in extra_paths:
        skip |= load_id_set_file(p)
    log(f"skip_labels loaded={len(skip):,}")
    return skip


def load_done_csv(path: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(float(r["id"]))
            except Exception:
                continue
            # skip failed rows for resume unless explicitly successful empty OCR
            if (r.get("error") or "").strip() and "ok" not in (r.get("error") or "").lower():
                # still treat non-empty error as done to avoid infinite retry loops;
                # force via deleting the row from checkpoint
                pass
            out[pid] = r
    return out


def write_csv(path: Path, fields: list[str], rows: dict[int, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _write_lock:
        with tmp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for pid in sorted(rows):
                w.writerow(rows[pid])
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)


def upload_results(*names: str) -> None:
    cli = s3()
    for name in names:
        p = QA / name
        if p.exists():
            cli.upload_file(str(p), BUCKET, s3_key("results", name))
            log(f"uploaded s3://{BUCKET}/{s3_key('results', name)}")


def ensure_ids_csv(api_key: str) -> Path:
    QA.mkdir(parents=True, exist_ok=True)
    if LOCAL_IDS.exists() and LOCAL_IDS.stat().st_size > 1000:
        return LOCAL_IDS
    # try pull from S3
    key = s3_key("results", "tmdb_horror_ids.csv")
    try:
        s3().download_file(BUCKET, key, str(LOCAL_IDS))
        if LOCAL_IDS.exists() and LOCAL_IDS.stat().st_size > 1000:
            log(f"pulled ids from s3://{BUCKET}/{key}")
            return LOCAL_IDS
    except Exception:
        pass
    log("enumerating TMDB horror ids (year-sharded)…")
    write_progress({"phase": "enumerate", "status": "running"})
    import tmdb_enumerate_horror as enum_mod

    # run as library
    os.environ["TMDB_API_KEY"] = api_key
    import sys

    sys.argv = [
        "tmdb_enumerate_horror.py",
        "--out", str(LOCAL_IDS),
        "--progress", str(QA / "enumerate_progress.json"),
    ]
    rc = enum_mod.main()
    if rc != 0:
        raise SystemExit(f"enumerate failed rc={rc}")
    s3().upload_file(str(LOCAL_IDS), BUCKET, key)
    s3().upload_file(str(LOCAL_IDS), BUCKET, s3_key("input", "tmdb_horror_ids.csv"))
    if (QA / "enumerate_progress.json").exists():
        s3().upload_file(str(QA / "enumerate_progress.json"), BUCKET, s3_key("results", "enumerate_progress.json"))
    write_progress({"phase": "enumerate", "status": "done", "n_ids": sum(1 for _ in LOCAL_IDS.open()) - 1})
    return LOCAL_IDS


def poster_key(pid: int) -> str:
    return s3_key("posters", f"{pid}.jpg")


def s3_exists(cli, key: str) -> bool:
    try:
        cli.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError:
        return False


def download_one(pid: int, poster_path: str) -> str:
    """Download TMDB poster and put to S3. Returns status string."""
    cli = s3()
    key = poster_key(pid)
    if s3_exists(cli, key):
        return "exists"
    if not poster_path or not poster_path.startswith("/"):
        return "no_path"
    url = IMG_BASE + poster_path
    try:
        r = session().get(url, headers=HEADERS, timeout=60)
        if r.status_code != 200:
            return f"http_{r.status_code}"
        if len(r.content) < 500:
            return "too_small"
        ctype = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
        cli.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=r.content,
            ContentType=ctype if ctype.startswith("image/") else "image/jpeg",
        )
        return "ok"
    except Exception as e:
        return f"err:{type(e).__name__}"


def phase_download(rows: list[dict], workers: int) -> dict:
    need = [(int(r["id"]), (r.get("poster_path") or "").strip()) for r in rows]
    # skip no_path early
    todo = [(pid, p) for pid, p in need if p.startswith("/")]
    no_path = len(need) - len(todo)
    log(f"download phase: candidates={len(todo):,} no_path={no_path:,} workers={workers}")
    write_progress({"phase": "download", "status": "running", "todo": len(todo), "no_path": no_path})

    # Filter already on S3 (batch via list? — head per id is OK with workers)
    cli = s3()
    missing: list[tuple[int, str]] = []
    existing = 0
    # faster: list all poster keys once
    existing_ids: set[int] = set()
    paginator = cli.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=s3_key("posters") + "/"):
        for obj in page.get("Contents") or []:
            name = obj["Key"].rsplit("/", 1)[-1]
            if name.endswith(".jpg"):
                try:
                    existing_ids.add(int(name[:-4]))
                except Exception:
                    pass
    for pid, p in todo:
        if pid in existing_ids:
            existing += 1
        else:
            missing.append((pid, p))
    log(f"s3 already has {existing:,} posters; downloading {len(missing):,}")

    ok = fail = 0
    t0 = time.time()
    manifest_path = QA / "download_manifest.csv"
    # append-friendly: load prior
    prior = {}
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    prior[int(r["id"])] = r
                except Exception:
                    pass
    for pid in existing_ids:
        prior.setdefault(pid, {"id": pid, "status": "exists", "error": ""})

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(download_one, pid, p): pid for pid, p in missing}
        for i, fut in enumerate(as_completed(futs), 1):
            pid = futs[fut]
            status = fut.result()
            if status in ("ok", "exists"):
                ok += 1
            else:
                fail += 1
            prior[pid] = {"id": pid, "status": status, "error": "" if status in ("ok", "exists") else status}
            if i % 100 == 0 or i == len(futs):
                rate = i / max(time.time() - t0, 1e-6)
                log(f"  dl {i}/{len(futs)} ok={ok} fail={fail} {rate:.1f}/s")
                write_csv(manifest_path, ["id", "status", "error"], prior)
                upload_results("download_manifest.csv")
                write_progress({
                    "phase": "download",
                    "status": "running",
                    "done": i,
                    "todo": len(futs),
                    "ok": ok,
                    "fail": fail,
                    "s3_existing_before": existing,
                })

    write_csv(manifest_path, ["id", "status", "error"], prior)
    upload_results("download_manifest.csv")
    summary = {
        "phase": "download",
        "status": "done",
        "s3_existing_before": existing,
        "downloaded_ok": ok,
        "fail": fail,
        "no_path": no_path,
        "s3_posters_approx": existing + ok,
    }
    write_progress(summary)
    return summary


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


def analyze_labels_s3(client, key: str, min_interval: float) -> dict:
    img = {"S3Object": {"Bucket": BUCKET, "Name": key}}

    lab = _call_with_retries(
        lambda: client.detect_labels(
            Image=img,
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

    mod = _call_with_retries(
        lambda: client.detect_moderation_labels(Image=img, MinConfidence=40),
        min_interval,
    )
    mods = [(m["Name"], float(m["Confidence"]) / 100.0) for m in mod.get("ModerationLabels", [])]
    mod_s = "|".join(f"{n}:{c:.2f}" for n, c in mods[:8])

    faces = _call_with_retries(
        lambda: client.detect_faces(Image=img, Attributes=["ALL"]),
        min_interval,
    )
    details = faces.get("FaceDetails") or []
    emotion = gender = ""
    age_lo = age_hi = -1
    if details:
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
        error="",
    )


def analyze_text_s3(client, key: str, min_interval: float) -> dict:
    t0 = time.time()
    img = {"S3Object": {"Bucket": BUCKET, "Name": key}}
    resp = _call_with_retries(lambda: client.detect_text(Image=img), min_interval)
    dets = resp.get("TextDetections") or []
    lines = [d for d in dets if d.get("Type") == "LINE"]
    words = [d for d in dets if d.get("Type") == "WORD"]
    lines = sorted(lines, key=lambda d: (d.get("Geometry", {}).get("BoundingBox", {}).get("Top", 0),
                                         d.get("Geometry", {}).get("BoundingBox", {}).get("Left", 0)))
    full = " ".join((d.get("DetectedText") or "").strip() for d in lines if (d.get("DetectedText") or "").strip())
    confs = [float(d.get("Confidence") or 0) for d in lines]
    mean_conf = round(sum(confs) / len(confs) / 100.0, 4) if confs else 0.0
    return {
        "full_ocr": full,
        "n_lines": len(lines),
        "n_words": len(words),
        "mean_conf": mean_conf,
        "latency_s": round(time.time() - t0, 3),
        "error": "",
    }


def list_s3_poster_ids() -> set[int]:
    cli = s3()
    ids: set[int] = set()
    paginator = cli.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=s3_key("posters") + "/"):
        for obj in page.get("Contents") or []:
            name = obj["Key"].rsplit("/", 1)[-1]
            if name.endswith(".jpg"):
                try:
                    ids.add(int(name[:-4]))
                except Exception:
                    pass
    return ids


def phase_labels(meta_by_id: dict[int, dict], skip: set[int], workers: int, min_interval: float, save_every: int) -> dict:
    out_path = QA / "rekognition_community_72k.csv"
    # resume from S3
    try:
        s3().download_file(BUCKET, s3_key("results", out_path.name), str(out_path))
    except Exception:
        pass
    rows = load_done_csv(out_path)
    have_poster = list_s3_poster_ids()
    todo = sorted(
        pid for pid in have_poster
        if pid not in skip and pid not in rows and pid in meta_by_id
    )
    # also allow posters without meta
    extra = sorted(pid for pid in have_poster if pid not in skip and pid not in rows and pid not in meta_by_id)
    todo = todo + extra
    log(f"labels phase: skip={len(skip):,} done={len(rows):,} todo={len(todo):,} workers={workers}")
    write_progress({"phase": "labels", "status": "running", "todo": len(todo), "done": len(rows), "skip": len(skip)})

    if not todo:
        write_progress({"phase": "labels", "status": "done", "done": len(rows), "todo": 0})
        return {"phase": "labels", "done": len(rows), "todo": 0}

    client = rek()
    ok = err = 0
    t0 = time.time()

    def one(pid: int) -> dict:
        meta = meta_by_id.get(pid) or {}
        try:
            feats = analyze_labels_s3(client, poster_key(pid), min_interval)
            return {
                "id": pid,
                "year": meta.get("year") or (meta.get("release_date") or "")[:4],
                "title": meta.get("title") or "",
                **feats,
            }
        except Exception as e:
            return {
                "id": pid,
                "year": meta.get("year") or "",
                "title": meta.get("title") or "",
                **{k: "" for k in LABEL_FIELDS if k not in ("id", "year", "title", "error")},
                "error": f"{type(e).__name__}: {e}"[:200],
            }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(one, pid): pid for pid in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            rows[int(row["id"])] = row
            if row.get("error"):
                err += 1
            else:
                ok += 1
            if i % save_every == 0 or i == len(futs):
                write_csv(out_path, LABEL_FIELDS, rows)
                upload_results(out_path.name)
                rate = i / max(time.time() - t0, 1e-6)
                log(f"  labels {i}/{len(futs)} ok={ok} err={err} {rate:.2f}/s")
                write_progress({
                    "phase": "labels",
                    "status": "running",
                    "done_batch": i,
                    "todo": len(futs),
                    "ok": ok,
                    "err": err,
                    "total_rows": len(rows),
                    "rate_per_s": round(rate, 3),
                })

    write_csv(out_path, LABEL_FIELDS, rows)
    upload_results(out_path.name)
    summary = {"phase": "labels", "status": "done", "ok": ok, "err": err, "total_rows": len(rows)}
    write_progress(summary)
    return summary


def phase_detecttext(meta_by_id: dict[int, dict], skip: set[int], workers: int, min_interval: float, save_every: int) -> dict:
    out_path = QA / "detecttext_community_72k.csv"
    try:
        s3().download_file(BUCKET, s3_key("results", out_path.name), str(out_path))
    except Exception:
        pass
    rows = load_done_csv(out_path)
    have_poster = list_s3_poster_ids()
    todo = sorted(pid for pid in have_poster if pid not in skip and pid not in rows)
    log(f"detecttext phase: skip={len(skip):,} done={len(rows):,} todo={len(todo):,} workers={workers}")
    write_progress({"phase": "detecttext", "status": "running", "todo": len(todo), "done": len(rows), "skip": len(skip)})

    if not todo:
        write_progress({"phase": "detecttext", "status": "done", "done": len(rows), "todo": 0})
        return {"phase": "detecttext", "done": len(rows), "todo": 0}

    client = rek()
    ok = err = 0
    t0 = time.time()

    def one(pid: int) -> dict:
        try:
            feats = analyze_text_s3(client, poster_key(pid), min_interval)
            return {"id": pid, **feats}
        except Exception as e:
            return {
                "id": pid,
                "full_ocr": "",
                "n_lines": 0,
                "n_words": 0,
                "mean_conf": 0,
                "latency_s": 0,
                "error": f"{type(e).__name__}: {e}"[:200],
            }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(one, pid): pid for pid in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            rows[int(row["id"])] = row
            if row.get("error"):
                err += 1
            else:
                ok += 1
            if i % save_every == 0 or i == len(futs):
                write_csv(out_path, TEXT_FIELDS, rows)
                upload_results(out_path.name)
                rate = i / max(time.time() - t0, 1e-6)
                log(f"  detecttext {i}/{len(futs)} ok={ok} err={err} {rate:.2f}/s")
                write_progress({
                    "phase": "detecttext",
                    "status": "running",
                    "done_batch": i,
                    "todo": len(futs),
                    "ok": ok,
                    "err": err,
                    "total_rows": len(rows),
                    "rate_per_s": round(rate, 3),
                })

    write_csv(out_path, TEXT_FIELDS, rows)
    upload_results(out_path.name)
    summary = {"phase": "detecttext", "status": "done", "ok": ok, "err": err, "total_rows": len(rows)}
    write_progress(summary)
    return summary


def get_api_key() -> str:
    env = (os.environ.get("TMDB_API_KEY") or "").strip()
    if env:
        return env
    for cand in (QA / "tmdb_api_key", DATA / "qa" / "tmdb_api_key", Path("data/qa/tmdb_api_key")):
        if cand.exists():
            return cand.read_text(encoding="utf-8").strip()
    raise SystemExit("TMDB_API_KEY missing")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=["all", "enumerate", "download", "labels", "detecttext"], default="all")
    ap.add_argument("--download-workers", type=int, default=24)
    ap.add_argument("--rek-workers", type=int, default=10)
    ap.add_argument("--min-interval", type=float, default=0.04)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--skip-labels-file", default=str(QA / "skip_labels_ids.txt"))
    ap.add_argument("--skip-text-file", default=str(QA / "skip_detecttext_ids.txt"))
    args = ap.parse_args()

    QA.mkdir(parents=True, exist_ok=True)
    log(f"community_72k_aws_worker bucket={BUCKET} prefix={PREFIX} phase={args.phase}")
    write_progress({"phase": args.phase, "status": "start"})

    api_key = ""
    if args.phase in ("all", "enumerate", "download"):
        api_key = get_api_key()

    if args.phase in ("all", "enumerate"):
        ensure_ids_csv(api_key or get_api_key())
        if args.phase == "enumerate":
            return 0

    ids_path = ensure_ids_csv(api_key or get_api_key()) if args.phase in ("all", "download") else LOCAL_IDS
    if not ids_path.exists():
        # pull
        try:
            s3().download_file(BUCKET, s3_key("results", "tmdb_horror_ids.csv"), str(LOCAL_IDS))
        except Exception:
            s3().download_file(BUCKET, s3_key("input", "tmdb_horror_ids.csv"), str(LOCAL_IDS))
    meta_rows = load_ids_csv(LOCAL_IDS)
    meta_by_id = {int(r["id"]): r for r in meta_rows}
    log(f"ids loaded={len(meta_by_id):,}")

    if args.phase in ("all", "download"):
        phase_download(meta_rows, args.download_workers)
        if args.phase == "download":
            return 0

    skip_text = load_id_set_file(Path(args.skip_text_file))
    for p in (QA / "skip_detecttext_ids.txt",):
        skip_text |= load_id_set_file(p)

    if args.phase in ("all", "labels"):
        # Gate + fresh skip: chain downloads skip once at boot; local enrich may still be writing.
        wait_if_pause_labels(poll_secs=float(os.environ.get("PAUSE_POLL_SECS", "30")))
        skip_labels = refresh_skip_from_s3(
            Path(args.skip_labels_file),
            QA / "skip_labels_ids.txt",
            DATA / "qa" / "community_72k" / "skip_labels_ids.txt",
        )
        write_progress({
            "phase": "labels",
            "status": "skip_refreshed",
            "skip": len(skip_labels),
        })
        phase_labels(meta_by_id, skip_labels, args.rek_workers, args.min_interval, args.save_every)
        if args.phase == "labels":
            return 0

    if args.phase in ("all", "detecttext"):
        phase_detecttext(meta_by_id, skip_text, args.rek_workers, args.min_interval, args.save_every)

    write_progress({"phase": "all", "status": "done", "n_ids": len(meta_by_id)})
    # DONE marker
    done = QA / "DONE"
    done.write_text(time.strftime("DONE_%Y%m%dT%H%M%SZ\n", time.gmtime()), encoding="utf-8")
    s3().upload_file(str(done), BUCKET, s3_key("results", "DONE"))
    log("ALL PHASES DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
