#!/bin/bash
# Stage OCR model pilot (~20–40 posters) to S3 — NOT the full corpus.
#
# Prerequisites: run dry-sample first (or pass N/SEED):
#   python3 pipeline/pilot_ocr_models.py --dry-sample --n 20 --seed 42
#
# Usage:
#   bash pipeline/aws/stage_ocr_pilot.sh
#   bash pipeline/aws/stage_ocr_pilot.sh --dry-run
#   N=40 SEED=7 bash pipeline/aws/stage_ocr_pilot.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
N="${N:-20}"
SEED="${SEED:-42}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

DRY=0
for a in "$@"; do
  [ "$a" = "--dry-run" ] && DRY=1
done

echo "=== stage_ocr_pilot → s3://$BUCKET/ocr_pilot/ (N=$N seed=$SEED) ==="

# Ensure sample ids exist
if [ ! -f data/qa/ocr_pilot/sample_ids.txt ]; then
  echo "--- building sample via --dry-sample ---"
  python3 pilot_ocr_models.py --dry-sample --n "$N" --seed "$SEED"
fi

STAGE=data/qa/_ocr_pilot_stage
rm -rf "$STAGE"
mkdir -p "$STAGE/code" "$STAGE/posters" "$STAGE/qa"

cp -f pilot_ocr_models.py "$STAGE/code/pilot_ocr_models.py"
cp -f aws/ocr_pilot_chain.sh "$STAGE/code/ocr_pilot_chain.sh"
cp -f aws/ocr_pilot_userdata.sh "$STAGE/code/ocr_pilot_userdata.sh"
cp -f data/qa/ocr_pilot/sample_ids.txt "$STAGE/qa/sample_ids.txt"
cp -f data/qa/ocr_pilot/sample_meta.csv "$STAGE/qa/sample_meta.csv" 2>/dev/null || true

# Minimal posters.csv subset for title/year join on the instance
python3 - <<'PY'
from pathlib import Path
import pandas as pd

ids = [int(x) for x in Path("data/qa/ocr_pilot/sample_ids.txt").read_text().split() if x.strip()]
p = pd.read_csv("data/posters.csv")
p = p[p["id"].astype(int).isin(ids)]
out = Path("data/qa/_ocr_pilot_stage/posters.csv")
p.to_csv(out, index=False)
print(f"posters.csv subset rows={len(p)} ids={len(ids)}")

stage = Path("data/qa/_ocr_pilot_stage/posters")
src = Path("data/posters")
ok = miss = 0
for pid in ids:
    s = src / f"{pid}.jpg"
    d = stage / f"{pid}.jpg"
    if not s.exists():
        miss += 1
        continue
    try:
        import os
        os.link(s, d)
    except OSError:
        import shutil
        shutil.copy2(s, d)
    ok += 1
print(f"staged jpgs={ok} missing={miss}")
if ok == 0:
    raise SystemExit("no posters staged")
PY

echo "jpg count: $(ls "$STAGE/posters"/*.jpg 2>/dev/null | wc -l | tr -d ' ')"
du -sh "$STAGE/posters"

if [ "$DRY" = "1" ]; then
  echo "DRY RUN — not uploading"
  ls -lh "$STAGE/code" "$STAGE/qa"
  exit 0
fi

echo "--- upload code + ids + subset posters.csv ---"
aws s3 cp "$STAGE/code/pilot_ocr_models.py" "s3://${BUCKET}/ocr_pilot/code/pilot_ocr_models.py"
aws s3 cp "$STAGE/code/ocr_pilot_chain.sh" "s3://${BUCKET}/ocr_pilot/code/ocr_pilot_chain.sh"
aws s3 cp "$STAGE/code/ocr_pilot_userdata.sh" "s3://${BUCKET}/ocr_pilot/code/ocr_pilot_userdata.sh"
aws s3 cp "$STAGE/qa/sample_ids.txt" "s3://${BUCKET}/ocr_pilot/sample_ids.txt"
aws s3 cp "$STAGE/posters.csv" "s3://${BUCKET}/ocr_pilot/posters.csv"
[ -f "$STAGE/qa/sample_meta.csv" ] && aws s3 cp "$STAGE/qa/sample_meta.csv" "s3://${BUCKET}/ocr_pilot/sample_meta.csv"

# Optional MODELS env for subset retries (chain also reads s3://…/ocr_pilot/MODELS)
if [ -n "${MODELS:-}" ]; then
  printf '%s\n' "$MODELS" | aws s3 cp - "s3://${BUCKET}/ocr_pilot/MODELS"
  echo "staged MODELS=$MODELS"
fi

# Keep prior results available for merge on subset re-runs
if [ -f data/qa/ocr_pilot/results.csv ]; then
  aws s3 cp data/qa/ocr_pilot/results.csv "s3://${BUCKET}/ocr_pilot/results/results.csv"
  echo "seeded prior results.csv for append-results merge"
fi

echo "--- sync sampled posters only ---"
aws s3 sync "$STAGE/posters/" "s3://${BUCKET}/ocr_pilot/posters/" --size-only

echo "LISTO — s3://${BUCKET}/ocr_pilot/"
echo "Siguiente: MODELS=… bash pipeline/aws/launch_ocr_pilot.sh"
