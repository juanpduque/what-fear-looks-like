#!/usr/bin/env python3
"""Pull Community-72k Rekognition results from S3 and merge into pipeline data.

Merges successful Labels rows into data/rekognition.csv (no id overlap expected
with main corpus). Saves DetectText sidecar as data/detecttext_community_72k.csv.

  python3 merge_community_72k.py              # use local qa/ copies if present
  python3 merge_community_72k.py --pull       # aws s3 cp results first
  python3 merge_community_72k.py --pull --lookup
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
QA = DATA / "qa" / "community_72k"
BUCKET = os.environ.get("BUCKET", "sagemaker-studio-a5572760")
PREFIX = os.environ.get("PREFIX", "wflike-community-72k")
REGION = os.environ.get("AWS_DEFAULT_REGION")

REK_OUT = DATA / "rekognition.csv"
REK_DECADE = DATA / "rekognition_decade.json"
DT_OUT = DATA / "detecttext_community_72k.csv"
MANIFEST_OUT = DATA / "qa" / "community_72k" / "download_manifest.csv"

RESULTS = [
    "rekognition_community_72k.csv",
    "detecttext_community_72k.csv",
    "download_manifest.csv",
    "DONE",
    "PROGRESS.json",
    "community_72k_relabels.log",
]


def pull_s3() -> None:
    if not REGION:
        raise SystemExit("AWS_DEFAULT_REGION required for --pull")
    QA.mkdir(parents=True, exist_ok=True)
    for name in RESULTS:
        key = f"s3://{BUCKET}/{PREFIX}/results/{name}"
        dest = QA / name
        cmd = ["aws", "s3", "cp", key, str(dest), "--region", REGION]
        print(f"pull {key}", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  skip/warn: {(r.stderr or r.stdout).strip()[:200]}", flush=True)
        else:
            print(f"  → {dest} ({dest.stat().st_size} bytes)", flush=True)


def decade_summary(df: pd.DataFrame) -> dict:
    if df.empty or "year" not in df.columns:
        return {}
    d = df.copy()
    d["year"] = pd.to_numeric(d["year"], errors="coerce")
    d = d.dropna(subset=["year"])
    d["decade"] = (d["year"] // 10 * 10).astype(int)
    out = {}
    for dec, g in d.groupby("decade"):
        out[str(int(dec))] = {
            "n": int(len(g)),
            "weapon": round(float((g.rek_weapon > 0.5).mean()), 4),
            "animal": round(float((g.rek_animal > 0.5).mean()), 4),
            "person": round(float((g.rek_person > 0.5).mean()), 4),
            "violence": round(float((g.rek_violence > 0.4).mean()), 4),
            "gore": round(float((g.rek_gore > 0.4).mean()), 4),
            "has_face": round(float((g.rek_n_faces > 0).mean()), 4),
            "silhouette": round(float((g.rek_silhouette > 0.5).mean()), 4),
        }
    return out


def merge_labels() -> dict:
    src = QA / "rekognition_community_72k.csv"
    if not src.exists():
        raise SystemExit(f"missing {src} — run with --pull")
    comm = pd.read_csv(src)
    if "error" in comm.columns:
        err = comm["error"].fillna("").astype(str).str.strip()
        bad = int((err != "").sum())
        ok = comm.loc[err == ""].drop(columns=["error"])
    else:
        bad = 0
        ok = comm
    # normalize types
    ok = ok.copy()
    ok["id"] = ok["id"].astype(int)
    main = pd.read_csv(REK_OUT) if REK_OUT.exists() else pd.DataFrame()
    before = len(main)
    overlap = set(main["id"].astype(int)) & set(ok["id"].astype(int)) if len(main) else set()
    if overlap:
        # community wins for overlapping ids (shouldn't happen for 72k gap set)
        main = main[~main["id"].astype(int).isin(overlap)]
    cols = list(main.columns) if len(main) else [c for c in ok.columns if c != "error"]
    for c in cols:
        if c not in ok.columns:
            ok[c] = "" if ok.select_dtypes(include="object").shape[1] else 0
    ok = ok[cols]
    merged = pd.concat([main, ok], ignore_index=True)
    merged = merged.drop_duplicates(subset=["id"], keep="last")
    merged = merged.sort_values("id").reset_index(drop=True)
    # backup
    if REK_OUT.exists():
        bak = DATA / f"rekognition_pre_community72k_{time.strftime('%Y%m%dT%H%M%SZ')}.csv"
        REK_OUT.replace(bak)
        print(f"backup {bak}", flush=True)
    merged.to_csv(REK_OUT, index=False)
    REK_DECADE.write_text(json.dumps(decade_summary(merged), indent=2) + "\n", encoding="utf-8")
    summary = {
        "community_ok": int(len(ok)),
        "community_err_skipped": bad,
        "overlap_replaced": len(overlap),
        "rekognition_before": before,
        "rekognition_after": int(len(merged)),
        "added": int(len(merged) - before + len(overlap)),
    }
    print(f"wrote {REK_OUT} {summary}", flush=True)
    return summary


def merge_detecttext() -> dict:
    src = QA / "detecttext_community_72k.csv"
    if not src.exists():
        raise SystemExit(f"missing {src}")
    dt = pd.read_csv(src)
    DT_OUT.parent.mkdir(parents=True, exist_ok=True)
    dt.to_csv(DT_OUT, index=False)
    err = dt["error"].fillna("").astype(str).str.strip() if "error" in dt.columns else pd.Series([""] * len(dt))
    summary = {
        "detecttext_rows": int(len(dt)),
        "detecttext_ok": int((err == "").sum()),
        "detecttext_err": int((err != "").sum()),
        "path": str(DT_OUT.relative_to(ROOT)),
    }
    print(f"wrote {DT_OUT} {summary}", flush=True)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pull", action="store_true", help="aws s3 cp results → qa/community_72k/")
    ap.add_argument("--lookup", action="store_true", help="rebuild site/data/lookup.js")
    args = ap.parse_args()
    if args.pull:
        pull_s3()
    labels = merge_labels()
    text = merge_detecttext()
    report = {
        "merged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bucket": BUCKET,
        "prefix": PREFIX,
        "labels": labels,
        "detecttext": text,
    }
    out = QA / "merge_report.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}", flush=True)
    if args.lookup:
        import build_lookup
        build_lookup.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
