#!/usr/bin/env python3
"""Pilot baselines: EasyOCR (cached) + AWS Rekognition + Google Vision OCR.

Runs on the SAME sample as pilot_ocr_models.py (sample_ids.txt) and merges
rows into data/qa/ocr_pilot/results.csv for models easyocr / rekognition / google
only (HF model rows are preserved).

  python3 pilot_ocr_cloud_baselines.py
  python3 pilot_ocr_cloud_baselines.py --models easyocr,rekognition,google
  python3 pilot_ocr_cloud_baselines.py --models easyocr  # no API calls

EasyOCR: join from data/poster_ocr.csv full_ocr (no re-run).
Rekognition: full DetectText → concatenate LINE texts (geometry-sorted).
Google: Vision TEXT_DETECTION (ADC / API key). If credentials missing → status skipped.
"""
from __future__ import annotations

import argparse
import base64
import csv
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

import pandas as pd

from ocr_metrics import title_overlap_score

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
POSTERS_CSV = DATA / "posters.csv"
POSTER_OCR_CSV = DATA / "poster_ocr.csv"
DEFAULT_OUT_DIR = DATA / "qa" / "ocr_pilot"
OUT_DIR = DEFAULT_OUT_DIR
RESULTS_CSV = OUT_DIR / "results.csv"
SAMPLE_IDS = OUT_DIR / "sample_ids.txt"

RESULT_FIELDS = [
    "id",
    "title",
    "year",
    "model",
    "text",
    "chars",
    "title_overlap_score",
    "latency_s",
    "status",
]

CLOUD_MODELS = ("easyocr", "rekognition", "google")
HF_MODELS = ("got", "deepseek", "paddle", "qianfan", "qwen")

REGION = "us-east-1"
DEFAULT_PROJECT = "playground-ia-502703"
VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


def configure_out_dir(path: str | Path) -> None:
    global OUT_DIR, RESULTS_CSV, SAMPLE_IDS
    OUT_DIR = Path(path)
    RESULTS_CSV = OUT_DIR / "results.csv"
    SAMPLE_IDS = OUT_DIR / "sample_ids.txt"


def load_sample(ids_file: Path) -> pd.DataFrame:
    posters = pd.read_csv(POSTERS_CSV, usecols=["id", "title", "year"])
    posters["id"] = posters["id"].astype(int)
    raw = ids_file.read_text(encoding="utf-8")
    ids = [int(x) for x in re.split(r"[\s,]+", raw.strip()) if x.strip()]
    df = posters[posters["id"].isin(ids)].copy()
    order = {pid: i for i, pid in enumerate(ids)}
    df["_ord"] = df["id"].map(order)
    return df.sort_values("_ord").drop(columns=["_ord"]).reset_index(drop=True)


def write_results(rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def append_result(rows: list[dict], row: dict) -> None:
    rows.append(row)
    write_results(rows)
    model_dir = OUT_DIR / row["model"]
    model_dir.mkdir(parents=True, exist_ok=True)
    if row.get("status") == "ok" and row.get("text"):
        # CSV stores escaped newlines; txt keeps raw multiline
        raw = str(row["text"]).replace("\\n", "\n")
        (model_dir / f"{row['id']}.txt").write_text(raw, encoding="utf-8")


def csv_text(text: str) -> str:
    return (text or "").replace("\n", "\\n")


def make_row(
    pid: int,
    title: str,
    year,
    model: str,
    text: str,
    latency_s: float,
    status: str,
) -> dict:
    ok = status == "ok"
    score = title_overlap_score(text, title) if ok else 0.0
    return {
        "id": pid,
        "title": title,
        "year": year,
        "model": model,
        "text": csv_text(text) if ok else "",
        "chars": len(text) if ok else 0,
        "title_overlap_score": score,
        "latency_s": round(latency_s, 3),
        "status": status,
    }


# ── EasyOCR (cached) ─────────────────────────────────────────────────────────


def run_easyocr(sample: pd.DataFrame, rows: list[dict]) -> None:
    print(f"\n=== model=easyocr (from {POSTER_OCR_CSV.name}) n={len(sample)} ===", flush=True)
    if not POSTER_OCR_CSV.exists():
        for _, r in sample.iterrows():
            append_result(
                rows,
                make_row(
                    int(r["id"]),
                    str(r.get("title") or ""),
                    r.get("year", ""),
                    "easyocr",
                    "",
                    0.0,
                    f"missing: {POSTER_OCR_CSV} not found",
                ),
            )
        return

    ocr = pd.read_csv(POSTER_OCR_CSV, usecols=["id", "full_ocr"])
    ocr["id"] = ocr["id"].astype(int)
    by_id = {int(i): ("" if pd.isna(t) else str(t)) for i, t in zip(ocr["id"], ocr["full_ocr"])}

    for _, r in sample.iterrows():
        pid = int(r["id"])
        title = str(r.get("title") or "")
        year = r.get("year", "")
        t0 = time.perf_counter()
        if pid not in by_id:
            status = "missing"
            text = ""
        else:
            text = by_id[pid].strip()
            status = "ok" if text else "missing"
        lat = time.perf_counter() - t0
        row = make_row(pid, title, year, "easyocr", text, lat, status)
        append_result(rows, row)
        print(
            f"  id={pid} status={status} chars={row['chars']} "
            f"overlap={row['title_overlap_score']} {row['latency_s']}s",
            flush=True,
        )


# ── AWS Rekognition ──────────────────────────────────────────────────────────


def _rekognition_lines(client, path: Path) -> list[dict]:
    data = path.read_bytes()
    if len(data) > 5_000_000:
        # Compress via Pillow to stay under 5 MB limit
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(data)).convert("RGB")
        buf = BytesIO()
        quality = 90
        while True:
            buf.seek(0)
            buf.truncate(0)
            img.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= 4_800_000 or quality <= 40:
                break
            quality -= 10
        data = buf.getvalue()

    resp = client.detect_text(Image={"Bytes": data})
    lines = []
    for d in resp.get("TextDetections", []):
        if d.get("Type") != "LINE":
            continue
        bb = d.get("Geometry", {}).get("BoundingBox") or {}
        lines.append(
            {
                "text": d.get("DetectedText", "") or "",
                "y0": float(bb.get("Top", 0.0)),
                "x0": float(bb.get("Left", 0.0)),
            }
        )
    lines.sort(key=lambda c: (round(c["y0"], 3), c["x0"]))
    return lines


def run_rekognition(sample: pd.DataFrame, rows: list[dict]) -> None:
    print(f"\n=== model=rekognition region={REGION} n={len(sample)} ===", flush=True)
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError

        client = boto3.client("rekognition", region_name=REGION)
    except Exception as e:
        msg = f"load_error: {e}"[:500]
        print(msg, flush=True)
        for _, r in sample.iterrows():
            append_result(
                rows,
                make_row(
                    int(r["id"]),
                    str(r.get("title") or ""),
                    r.get("year", ""),
                    "rekognition",
                    "",
                    0.0,
                    msg,
                ),
            )
        return

    for _, r in sample.iterrows():
        pid = int(r["id"])
        title = str(r.get("title") or "")
        year = r.get("year", "")
        img = POSTERS / f"{pid}.jpg"
        t0 = time.perf_counter()
        status = "ok"
        text = ""
        try:
            if not img.exists():
                raise FileNotFoundError(f"missing {img}")
            lines = _rekognition_lines(client, img)
            text = "\n".join(ln["text"] for ln in lines if ln["text"]).strip()
            if not text:
                status = "ok"  # API succeeded, empty OCR
        except (ClientError, BotoCoreError, OSError, ValueError) as e:
            status = f"error: {e}"[:500]
            print(f"  id={pid} FAIL {status}", flush=True)
            traceback.print_exc()
        except Exception as e:
            status = f"error: {e}"[:500]
            print(f"  id={pid} FAIL {status}", flush=True)
            traceback.print_exc()
        lat = time.perf_counter() - t0
        row = make_row(pid, title, year, "rekognition", text, lat, status)
        append_result(rows, row)
        # write raw multiline even when empty-ok
        if status == "ok" and text:
            (OUT_DIR / "rekognition" / f"{pid}.txt").write_text(text, encoding="utf-8")
        print(
            f"  id={pid} status={status[:40]} chars={row['chars']} "
            f"overlap={row['title_overlap_score']} {row['latency_s']}s",
            flush=True,
        )


# ── Google Vision ─────────────────────────────────────────────────────────────


def _google_api_key() -> str:
    for env in ("GOOGLE_API_KEY", "VISION_API_KEY", "GOOGLE_VISION_API_KEY"):
        v = (os.environ.get(env) or "").strip()
        if v:
            return v
    return ""


def _google_access_token() -> str | None:
    """Return Bearer token, or None if credentials unavailable."""
    # Prefer google.auth (works with GOOGLE_APPLICATION_CREDENTIALS or ADC)
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        req = google.auth.transport.requests.Request()
        creds.refresh(req)
        if creds.token:
            return creds.token
    except Exception as e:
        print(f"  google.auth unavailable: {e}", flush=True)

    # Fallback: gcloud ADC (same as title_boxes_vision_pilot.py)
    try:
        tok = subprocess.check_output(
            ["gcloud", "auth", "application-default", "print-access-token"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
        if tok:
            return tok
    except Exception as e:
        print(f"  gcloud ADC unavailable: {e}", flush=True)

    return None


def _vision_full_text(
    session,
    path: Path,
    *,
    token: str | None,
    api_key: str,
    project: str,
) -> str:
    import requests

    raw = path.read_bytes()
    if len(raw) > 20_000_000:
        raise ValueError(f"image too large: {len(raw)}")

    body = {
        "requests": [
            {
                "image": {"content": base64.b64encode(raw).decode()},
                "features": [{"type": "TEXT_DETECTION"}],
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    params = None
    if api_key:
        params = {"key": api_key}
    elif token:
        headers["Authorization"] = f"Bearer {token}"
        headers["x-goog-user-project"] = project
    else:
        raise RuntimeError("no Google credentials")

    r = session.post(VISION_URL, headers=headers, params=params, json=body, timeout=60)
    if r.status_code == 401:
        raise RuntimeError("Vision 401 — re-auth: gcloud auth application-default login")
    if r.status_code == 429:
        time.sleep(2)
        return _vision_full_text(
            session, path, token=token, api_key=api_key, project=project
        )
    if not r.ok:
        raise RuntimeError(f"Vision HTTP {r.status_code}: {r.text[:300]}")
    resp = (r.json().get("responses") or [{}])[0]
    if "error" in resp:
        err = resp["error"]
        raise RuntimeError(err if isinstance(err, str) else err.get("message", str(err)))
    anns = resp.get("textAnnotations") or []
    if not anns:
        return ""
    return (anns[0].get("description") or "").strip()


def run_google(sample: pd.DataFrame, rows: list[dict], project: str) -> None:
    print(f"\n=== model=google project={project} n={len(sample)} ===", flush=True)
    api_key = _google_api_key()
    token = None if api_key else _google_access_token()

    if not api_key and not token:
        msg = (
            "skipped: no Google credentials "
            "(need gcloud ADC / GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_API_KEY)"
        )
        print(msg, flush=True)
        for _, r in sample.iterrows():
            append_result(
                rows,
                make_row(
                    int(r["id"]),
                    str(r.get("title") or ""),
                    r.get("year", ""),
                    "google",
                    "",
                    0.0,
                    msg,
                ),
            )
        return

    try:
        import requests
    except ImportError as e:
        msg = f"load_error: {e}"[:500]
        for _, r in sample.iterrows():
            append_result(
                rows,
                make_row(
                    int(r["id"]),
                    str(r.get("title") or ""),
                    r.get("year", ""),
                    "google",
                    "",
                    0.0,
                    msg,
                ),
            )
        return

    session = requests.Session()
    for _, r in sample.iterrows():
        pid = int(r["id"])
        title = str(r.get("title") or "")
        year = r.get("year", "")
        img = POSTERS / f"{pid}.jpg"
        t0 = time.perf_counter()
        status = "ok"
        text = ""
        try:
            if not img.exists():
                raise FileNotFoundError(f"missing {img}")
            text = _vision_full_text(
                session, img, token=token, api_key=api_key, project=project
            )
        except Exception as e:
            status = f"error: {e}"[:500]
            print(f"  id={pid} FAIL {status}", flush=True)
            traceback.print_exc()
        lat = time.perf_counter() - t0
        row = make_row(pid, title, year, "google", text, lat, status)
        append_result(rows, row)
        if status == "ok" and text:
            (OUT_DIR / "google" / f"{pid}.txt").write_text(text, encoding="utf-8")
        print(
            f"  id={pid} status={status[:40]} chars={row['chars']} "
            f"overlap={row['title_overlap_score']} {row['latency_s']}s",
            flush=True,
        )


# ── comparison table ──────────────────────────────────────────────────────────


def print_comparison(rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    if df.empty:
        print("\n(no results)", flush=True)
        return

    df["title_overlap_score"] = pd.to_numeric(df["title_overlap_score"], errors="coerce")
    df["chars"] = pd.to_numeric(df["chars"], errors="coerce")
    df["latency_s"] = pd.to_numeric(df["latency_s"], errors="coerce")

    order = list(HF_MODELS) + list(CLOUD_MODELS)
    models = [m for m in order if m in set(df["model"])] + [
        m for m in sorted(df["model"].unique()) if m not in order
    ]

    print("\n=== comparison (mean title_overlap / chars / latency; ok rate) ===", flush=True)
    lines = []
    for m in models:
        g = df[df["model"] == m]
        ok = g["status"].astype(str).eq("ok")
        n_ok = int(ok.sum())
        n = len(g)
        # overlap on ok rows only (failed/skipped stay 0 in CSV)
        ov = g.loc[ok, "title_overlap_score"].mean() if n_ok else float("nan")
        ch = g.loc[ok, "chars"].mean() if n_ok else float("nan")
        lat = g.loc[ok, "latency_s"].mean() if n_ok else float("nan")
        # also report mean overlap over all sample rows (incl. 0 for fails)
        ov_all = g["title_overlap_score"].mean()
        lines.append(
            {
                "model": m,
                "n": n,
                "ok": n_ok,
                "ok_pct": round(100.0 * n_ok / n, 1) if n else 0.0,
                "mean_overlap": round(float(ov), 4) if n_ok else None,
                "mean_overlap_all": round(float(ov_all), 4),
                "mean_chars": round(float(ch), 1) if n_ok else None,
                "mean_latency_s": round(float(lat), 3) if n_ok else None,
            }
        )

    summary = pd.DataFrame(lines).sort_values(
        "mean_overlap_all", ascending=False, na_position="last"
    )
    print(summary.to_string(index=False), flush=True)
    print("\nRanking by mean title_overlap (all rows):", flush=True)
    for i, r in enumerate(summary.itertuples(index=False), 1):
        ov = r.mean_overlap_all
        print(
            f"  {i:2d}. {r.model:12s}  overlap={ov:.4f}  "
            f"ok={r.ok}/{r.n}  chars≈{r.mean_chars}  latency≈{r.mean_latency_s}s",
            flush=True,
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--ids-file",
        default=str(SAMPLE_IDS),
        help="sample id list (default: data/qa/ocr_pilot/sample_ids.txt)",
    )
    ap.add_argument(
        "--models",
        default="easyocr,rekognition,google",
        help="comma-separated: easyocr,rekognition,google",
    )
    ap.add_argument(
        "--project",
        default=os.environ.get("GCP_PROJECT", DEFAULT_PROJECT),
        help="GCP project for Vision (x-goog-user-project)",
    )
    ap.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="output dir (default: data/qa/ocr_pilot)",
    )
    args = ap.parse_args()
    configure_out_dir(args.out_dir)
    if args.ids_file == str(DEFAULT_OUT_DIR / "sample_ids.txt") and OUT_DIR != DEFAULT_OUT_DIR:
        # if user only changed out-dir, default ids to that dir
        args.ids_file = str(OUT_DIR / "sample_ids.txt")

    keys = [k.strip().lower() for k in args.models.split(",") if k.strip()]
    for k in keys:
        if k not in CLOUD_MODELS:
            raise SystemExit(f"unknown model '{k}'; choose from {list(CLOUD_MODELS)}")

    ids_path = Path(args.ids_file)
    if not ids_path.exists():
        raise SystemExit(f"missing ids file: {ids_path}")

    sample = load_sample(ids_path)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"sample n={len(sample)} from {ids_path}", flush=True)
    print(sample[["id", "title", "year"]].to_string(index=False), flush=True)

    # Keep prior rows for models not being re-run
    rows: list[dict] = []
    if RESULTS_CSV.exists():
        with RESULTS_CSV.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                if r.get("model") not in keys:
                    rows.append(r)
        print(
            f"kept {len(rows)} prior rows for models outside {keys}",
            flush=True,
        )

    for key in keys:
        rows = [r for r in rows if r.get("model") != key]
        if key == "easyocr":
            run_easyocr(sample, rows)
        elif key == "rekognition":
            run_rekognition(sample, rows)
        elif key == "google":
            run_google(sample, rows, args.project)

    write_results(rows)
    print(f"\nLISTO → {RESULTS_CSV} ({len(rows)} rows)", flush=True)
    print_comparison(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
