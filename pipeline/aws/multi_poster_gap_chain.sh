#!/bin/bash
# Multi-poster GAP on EC2: discover → download → embed(merge) → select → OCR score → S3.
# Extends existing catalog/canonical/clusters/embeddings; does NOT rebuild clip_embeddings.npz.
# Apply-swaps is DEFERRED (swaps CSV only).
set -euo pipefail
export PATH=/usr/local/bin:${PATH:-}
export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-multi-poster-gap}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export POSTER_SRC="${POSTER_SRC:-s3://sagemaker-studio-a5572760/wflike-community-72k/posters}"
export VISION_GAP_POSTERS="${VISION_GAP_POSTERS:-s3://sagemaker-studio-a5572760/wflike-vision-gap/input/posters}"
export SYNC_SECS="${SYNC_SECS:-180}"
export DL_WORKERS="${DL_WORKERS:-24}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-16}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-16}"
export TORCH_NUM_THREADS="${TORCH_NUM_THREADS:-16}"
export OCR_WORKERS="${OCR_WORKERS:-8}"

ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
DATA=$PIPE/data
QA=$DATA/qa/multi_poster_gap
LOG=$DATA/multi_poster_gap_aws.log
mkdir -p "$DATA/posters" "$DATA/posters_multi" "$QA" "$DATA/qa"
exec > >(tee -a "$LOG") 2>&1

echo "=== multi_poster_gap_chain start $(date -u) ==="
cd "$PIPE"

on_err() {
  ec=$?
  echo "ERROR trap ec=$ec phase=$(cat /tmp/mpg_phase 2>/dev/null || echo unknown) $(date -u)" || true
  echo "FAIL" > "$QA/FAIL" 2>/dev/null || true
  date -u +"MULTI_POSTER_GAP_ERR_%Y%m%dT%H%M%SZ ec=$ec" >> "$QA/FAIL" 2>/dev/null || true
  aws s3 cp "$QA/FAIL" "s3://${BUCKET}/${PREFIX}/results/FAIL" --quiet 2>/dev/null || true
  sync_out || true
  sleep 10
  sudo shutdown -h now || true
}
trap on_err ERR

aws sts get-caller-identity || true

# TMDB key: ENV file, staged secret, or ROOT/.tmdb_key
if [ -z "${TMDB_API_KEY:-}" ]; then
  for cand in \
    "$QA/tmdb_api_key" \
    "$DATA/qa/tmdb_api_key" \
    "$ROOT/.tmdb_key"
  do
    if [ -f "$cand" ]; then
      TMDB_API_KEY="$(tr -d ' \n\r' < "$cand")"
      export TMDB_API_KEY
      break
    fi
  done
fi
if [ -z "${TMDB_API_KEY:-}" ]; then
  echo "FATAL: TMDB_API_KEY missing"; exit 1
fi
echo "TMDB_API_KEY present (len=${#TMDB_API_KEY})"

write_progress() {
  python3 - <<'PY'
import json, time
from pathlib import Path
DATA = Path("data")
QA = DATA / "qa" / "multi_poster_gap"

def nids(p, col="id"):
    try:
        import pandas as pd
        return int(pd.read_csv(p, usecols=[col])[col].nunique())
    except Exception:
        return 0

def nkeys(p):
    try:
        import numpy as np
        return int(len(np.load(p)["keys"]))
    except Exception:
        return 0

phase = open("/tmp/mpg_phase").read().strip() if Path("/tmp/mpg_phase").exists() else "unknown"
todo_n = 0
tp = QA / "todo_ids.txt"
if tp.exists():
    todo_n = sum(1 for ln in tp.read_text().splitlines() if ln.strip())

doc = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "phase": phase,
    "n_todo_seed": todo_n,
    "catalog_ids": nids(DATA / "multi_poster_catalog.csv"),
    "canonical_ids": nids(DATA / "multi_poster_canonical.csv"),
    "cluster_rows": 0,
    "embed_keys": nkeys(DATA / "multi_poster_embeddings.npz") or nkeys(DATA / "multi_poster_embeddings_partial.npz"),
    "posters_multi_dirs": sum(1 for _ in (DATA / "posters_multi").glob("*") if _.is_dir()) if (DATA / "posters_multi").exists() else 0,
    "ocr_score_rows": 0,
    "ocr_swaps_proposed": 0,
}
try:
    import pandas as pd
    if (DATA / "multi_poster_clusters.csv").exists():
        doc["cluster_rows"] = int(len(pd.read_csv(DATA / "multi_poster_clusters.csv")))
    sc = DATA / "qa" / "multi_poster_variant_ocr_scores.csv"
    sw = DATA / "qa" / "multi_poster_variant_ocr_swaps.csv"
    if sc.exists():
        doc["ocr_score_rows"] = int(len(pd.read_csv(sc)))
    if sw.exists():
        s = pd.read_csv(sw)
        doc["ocr_swaps_proposed"] = int((s["propose"] == 1).sum()) if "propose" in s.columns else 0
except Exception:
    pass
(QA / "PROGRESS.json").write_text(json.dumps(doc, indent=2) + "\n")
print(json.dumps(doc))
PY
  aws s3 cp "$QA/PROGRESS.json" "s3://${BUCKET}/${PREFIX}/results/PROGRESS.json" --quiet || true
  aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/multi_poster_gap_aws.log" --quiet || true
}

sync_out() {
  for f in multi_poster_catalog.csv multi_poster_canonical.csv multi_poster_clusters.csv \
           multi_poster_embeddings.npz multi_poster_embeddings_partial.npz multi_poster_gap_aws.log; do
    [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/${PREFIX}/results/$f" --quiet || true
  done
  for f in multi_poster_variant_ocr_scores.csv multi_poster_variant_ocr_swaps.csv; do
    [ -f "data/qa/$f" ] && aws s3 cp "data/qa/$f" "s3://${BUCKET}/${PREFIX}/results/qa/$f" --quiet || true
  done
  [ -f "$QA/PROGRESS.json" ] && \
    aws s3 cp "$QA/PROGRESS.json" "s3://${BUCKET}/${PREFIX}/results/PROGRESS.json" --quiet || true
  [ -f "$QA/gap_report.json" ] && \
    aws s3 cp "$QA/gap_report.json" "s3://${BUCKET}/${PREFIX}/results/gap_report.json" --quiet || true
  write_progress
}

echo "boot" > /tmp/mpg_phase
write_progress

# ---- deps ----
echo "--- apt/pip ---"
for n in 1 2 3 4 5 6 7 8; do
  if sudo apt-get update -y && sudo apt-get install -y python3-pip python3-venv curl ca-certificates unzip; then
    break
  fi
  echo "apt failed attempt $n — regional mirror"
  sudo sed -i.bak \
    -e 's|http://[a-zA-Z0-9.-]*archive.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
    -e 's|https://[a-zA-Z0-9.-]*archive.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
    -e 's|http://security.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
    /etc/apt/sources.list || true
  sleep $((n * 15))
done

VENV=/home/ubuntu/aof/.venv-mpg
rm -rf "$VENV" 2>/dev/null || true
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
export PATH="$VENV/bin:/usr/local/bin:$PATH"
python -m pip -q install -U pip
python -m pip -q install -U requests pandas numpy pillow boto3 botocore
python -m pip -q install -U torch --index-url https://download.pytorch.org/whl/cpu
python -m pip -q install -U open_clip_torch

# Prefer cloud results seed if present (resume), else keep staged input/
echo "--- seed / resume from results if present ---"
for f in multi_poster_catalog.csv multi_poster_canonical.csv multi_poster_clusters.csv \
         multi_poster_embeddings.npz multi_poster_embeddings_partial.npz; do
  if aws s3 ls "s3://${BUCKET}/${PREFIX}/results/$f" >/dev/null 2>&1; then
    echo "resume $f from results/"
    aws s3 cp "s3://${BUCKET}/${PREFIX}/results/$f" "data/$f"
  fi
done
for f in multi_poster_variant_ocr_scores.csv multi_poster_variant_ocr_swaps.csv; do
  if aws s3 ls "s3://${BUCKET}/${PREFIX}/results/qa/$f" >/dev/null 2>&1; then
    echo "resume qa/$f from results/"
    aws s3 cp "s3://${BUCKET}/${PREFIX}/results/qa/$f" "data/qa/$f"
  fi
done

IDS_FILE="$QA/todo_ids.txt"
[ -f "$IDS_FILE" ] || IDS_FILE="$QA/todo_ids.csv"
[ -f "$IDS_FILE" ] || { echo "FATAL: missing todo_ids"; exit 1; }
[ -f data/posters.csv ] || { echo "FATAL: missing data/posters.csv"; exit 1; }
[ -f data/multi_poster_catalog.csv ] || echo "WARN: no seed catalog — discover starts fresh for todo ids"

(
  while true; do
    sleep "${SYNC_SECS}"
    sync_out || true
    echo "[checkpoint $(date -u +%H:%M:%S)] synced multi-poster-gap artifacts" || true
  done
) &
CKPID=$!

# ---- discover ----
echo "discover" > /tmp/mpg_phase
echo "--- discover (ids-file=$IDS_FILE) ---"
python -u multi_poster_pipeline.py discover \
  --ids-file "$IDS_FILE" \
  --langs en,null \
  --max-list 20 \
  --sleep 0.03
sync_out

# ---- download ----
echo "download" > /tmp/mpg_phase
echo "--- download ---"
python -u multi_poster_pipeline.py download --max-per-id 5 --workers "${DL_WORKERS}"
sync_out

# ---- embed (merge into existing npz) ----
echo "embed" > /tmp/mpg_phase
echo "--- embed (merge) ---"
python -u multi_poster_pipeline.py embed --max-per-id 5
sync_out

# ---- select / report (full catalog refresh; no --apply to posters/) ----
echo "select" > /tmp/mpg_phase
echo "--- select + report ---"
python -u multi_poster_pipeline.py select --sim 0.96 --max-per-id 5
python -u multi_poster_pipeline.py report
sync_out

# ---- OCR score gap films with ≥2 local variants (swaps propose only; apply deferred) ----
echo "ocr" > /tmp/mpg_phase
echo "--- OCR score (gap multi-variant; apply-swaps DEFERRED) ---"
python3 - <<'PY'
"""Build OCR ids CSV: gap todo ∩ posters_multi dirs with ≥2 jpgs."""
from pathlib import Path
import pandas as pd

QA = Path("data/qa/multi_poster_gap")
MULTI = Path("data/posters_multi")
todo = set()
for p in (QA / "todo_ids.txt", QA / "todo_ids.csv"):
    if not p.exists():
        continue
    if p.suffix == ".csv":
        todo |= set(pd.read_csv(p, usecols=["id"])["id"].astype(int))
    else:
        todo |= {int(x) for x in p.read_text().splitlines() if x.strip().isdigit()}
    break

rows = []
for d in sorted(MULTI.glob("*")):
    if not d.is_dir():
        continue
    try:
        pid = int(d.name)
    except Exception:
        continue
    if todo and pid not in todo:
        continue
    n = sum(1 for _ in d.glob("*.jpg"))
    if n >= 2:
        rows.append({"id": pid, "n_variants": n})

out = QA / "ocr_gap_ids.csv"
pd.DataFrame(rows).to_csv(out, index=False)
print(f"ocr candidates (ge2): {len(rows):,} → {out}")
PY

# Sync primary posters for OCR baseline (S3→disk, gap ocr ids only)
if [ -f "$QA/ocr_gap_ids.csv" ]; then
  echo "--- sync primary posters for OCR candidates ---"
  python3 - <<'PY'
import subprocess
from pathlib import Path
import pandas as pd
import os

ids = pd.read_csv("data/qa/multi_poster_gap/ocr_gap_ids.csv", usecols=["id"])["id"].astype(int).tolist()
posters = Path("data/posters")
posters.mkdir(parents=True, exist_ok=True)
srcs = [
    os.environ.get("POSTER_SRC", "").rstrip("/"),
    os.environ.get("VISION_GAP_POSTERS", "").rstrip("/"),
]
ok = miss = 0
for pid in ids:
    dest = posters / f"{pid}.jpg"
    if dest.exists() and dest.stat().st_size > 2000:
        ok += 1
        continue
    got = False
    for src in srcs:
        if not src:
            continue
        uri = f"{src}/{pid}.jpg"
        r = subprocess.run(
            ["aws", "s3", "cp", uri, str(dest), "--quiet"],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and dest.exists() and dest.stat().st_size > 2000:
            got = True
            break
        dest.unlink(missing_ok=True)
    if got:
        ok += 1
    else:
        miss += 1
print(f"primary posters ok={ok} miss={miss} of {len(ids)}")
PY
fi

if [ -f "$QA/ocr_gap_ids.csv" ] && [ "$(wc -l < "$QA/ocr_gap_ids.csv")" -gt 1 ]; then
  python -u score_multi_poster_variants_ocr.py \
    --ids-file "$QA/ocr_gap_ids.csv" \
    --ge2-only \
    --workers "${OCR_WORKERS}" \
    --min-interval 0.08
else
  echo "OCR skipped — no ge2 candidates"
fi
# NOTE: apply_multi_poster_ocr_swaps.py intentionally NOT run (deferred; swaps CSV only)
echo "OCR apply-swaps DEFERRED — see results/qa/multi_poster_variant_ocr_swaps.csv"
sync_out

kill "$CKPID" 2>/dev/null || true

echo "done" > /tmp/mpg_phase
write_progress
date -u +"MULTI_POSTER_GAP_DONE_%Y%m%dT%H%M%SZ" > "$QA/DONE"
echo "apply_swaps=deferred" >> "$QA/DONE"
aws s3 cp "$QA/DONE" "s3://${BUCKET}/${PREFIX}/results/DONE"
aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/multi_poster_gap_aws.log"
echo "=== multi_poster_gap_chain done $(date -u) ==="
sleep 20
sudo shutdown -h now
