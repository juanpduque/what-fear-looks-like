#!/bin/bash
# Stage OCR pilot v2 (n≈100 stratified) to S3 — sample JPGs only.
#
# Prerequisites:
#   python3 build_ocr_pilot_sample.py --n 100 --seed 42
#
# Usage:
#   bash aws/stage_ocr_pilot_v2.sh
#   MODELS=qwen,deepseek,paddle,qianfan,got bash aws/stage_ocr_pilot_v2.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_pilot_v2}"
MAX_N="${MAX_N:-120}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

echo "=== stage_${PREFIX} → s3://$BUCKET/${PREFIX}/ ==="

if [ ! -f "data/qa/${PREFIX}/sample_ids.txt" ]; then
  echo "--- building sample ---"
  python3 build_ocr_pilot_sample.py --n 100 --seed 42 --out-dir "data/qa/${PREFIX}"
fi

N_LOCAL=$(wc -l < "data/qa/${PREFIX}/sample_ids.txt" | tr -d ' ')
if [ "$N_LOCAL" -gt "$MAX_N" ]; then
  echo "ERROR: sample has $N_LOCAL ids — refuse >$MAX_N"; exit 1
fi

STAGE="data/qa/_${PREFIX}_stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/code" "$STAGE/posters" "$STAGE/qa"

cp -f pilot_ocr_models.py "$STAGE/code/pilot_ocr_models.py"
cp -f ocr_metrics.py "$STAGE/code/ocr_metrics.py"
cp -f "aws/${PREFIX}_chain.sh" "$STAGE/code/${PREFIX}_chain.sh" 2>/dev/null \
  || cp -f aws/ocr_pilot_v2_chain.sh "$STAGE/code/ocr_pilot_v2_chain.sh"
cp -f "aws/${PREFIX}_userdata.sh" "$STAGE/code/${PREFIX}_userdata.sh" 2>/dev/null \
  || cp -f aws/ocr_pilot_v2_userdata.sh "$STAGE/code/ocr_pilot_v2_userdata.sh"
cp -f "data/qa/${PREFIX}/sample_ids.txt" "$STAGE/qa/sample_ids.txt"
cp -f "data/qa/${PREFIX}/sample_meta.csv" "$STAGE/qa/sample_meta.csv" 2>/dev/null || true

python3 - <<PY
from pathlib import Path
import pandas as pd
import os, shutil

prefix = "${PREFIX}"
ids = [int(x) for x in Path(f"data/qa/{prefix}/sample_ids.txt").read_text().split() if x.strip()]
p = pd.read_csv("data/posters.csv")
p = p[p["id"].astype(int).isin(ids)]
stage = Path(f"data/qa/_{prefix}_stage")
p.to_csv(stage / "posters.csv", index=False)
print(f"posters.csv subset rows={len(p)} ids={len(ids)}")
dst = stage / "posters"
src = Path("data/posters")
ok = miss = 0
for pid in ids:
    s = src / f"{pid}.jpg"
    d = dst / f"{pid}.jpg"
    if not s.exists():
        miss += 1
        continue
    try:
        os.link(s, d)
    except OSError:
        shutil.copy2(s, d)
    ok += 1
print(f"staged jpgs={ok} missing={miss}")
if ok == 0:
    raise SystemExit("no posters staged")
PY

echo "jpg count: $(ls "$STAGE/posters"/*.jpg 2>/dev/null | wc -l | tr -d ' ')"

echo "--- upload code + ids + subset posters.csv ---"
aws s3 cp "$STAGE/code/pilot_ocr_models.py" "s3://${BUCKET}/${PREFIX}/code/pilot_ocr_models.py"
aws s3 cp "$STAGE/code/ocr_metrics.py" "s3://${BUCKET}/${PREFIX}/code/ocr_metrics.py"
aws s3 cp "$STAGE/code/ocr_pilot_v2_chain.sh" "s3://${BUCKET}/${PREFIX}/code/ocr_pilot_v2_chain.sh"
aws s3 cp "$STAGE/code/ocr_pilot_v2_userdata.sh" "s3://${BUCKET}/${PREFIX}/code/ocr_pilot_v2_userdata.sh"
aws s3 cp "$STAGE/qa/sample_ids.txt" "s3://${BUCKET}/${PREFIX}/sample_ids.txt"
aws s3 cp "$STAGE/posters.csv" "s3://${BUCKET}/${PREFIX}/posters.csv"
[ -f "$STAGE/qa/sample_meta.csv" ] && aws s3 cp "$STAGE/qa/sample_meta.csv" "s3://${BUCKET}/${PREFIX}/sample_meta.csv"

if [ -n "${MODELS:-}" ]; then
  printf '%s\n' "$MODELS" | aws s3 cp - "s3://${BUCKET}/${PREFIX}/MODELS"
  echo "staged MODELS=$MODELS"
fi

if [ -f "data/qa/${PREFIX}/results.csv" ]; then
  aws s3 cp "data/qa/${PREFIX}/results.csv" "s3://${BUCKET}/${PREFIX}/results/results.csv"
  echo "seeded prior results.csv for append-results merge"
fi

echo "--- sync sampled posters only ---"
aws s3 sync "$STAGE/posters/" "s3://${BUCKET}/${PREFIX}/posters/" --size-only

echo "LISTO — s3://${BUCKET}/${PREFIX}/"
echo "Siguiente: MODELS=… bash aws/launch_ocr_pilot_v2.sh"
