#!/bin/bash
# Stage hard-set posters + code for text-det → crop → Qwen OCR.
# Reuses the 12 hard ids / poster_sources from ocr_qwen_hard (no fake homolog).
#
# Usage:
#   bash aws/stage_ocr_qwen_hard_crop.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_qwen_hard_crop}"
SRC_PREFIX="${SRC_PREFIX:-ocr_qwen_hard}"
MAX_N="${MAX_N:-120}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

echo "=== stage_${PREFIX} → s3://$BUCKET/${PREFIX}/ ==="

mkdir -p "data/qa/${PREFIX}"

# Reuse hard sample ids + meta + poster_sources from prior hard run
if [ ! -f "data/qa/${SRC_PREFIX}/sample_ids.txt" ]; then
  echo "ERROR: missing data/qa/${SRC_PREFIX}/sample_ids.txt"; exit 1
fi
cp -f "data/qa/${SRC_PREFIX}/sample_ids.txt" "data/qa/${PREFIX}/sample_ids.txt"
[ -f "data/qa/${SRC_PREFIX}/sample_meta.csv" ] && \
  cp -f "data/qa/${SRC_PREFIX}/sample_meta.csv" "data/qa/${PREFIX}/sample_meta.csv"
[ -f "data/qa/${SRC_PREFIX}/poster_sources.csv" ] && \
  cp -f "data/qa/${SRC_PREFIX}/poster_sources.csv" "data/qa/${PREFIX}/poster_sources.csv"

N_LOCAL=$(wc -l < "data/qa/${PREFIX}/sample_ids.txt" | tr -d ' ')
if [ "$N_LOCAL" -gt "$MAX_N" ]; then
  echo "ERROR: sample has $N_LOCAL ids — refuse >$MAX_N"; exit 1
fi
if [ "$N_LOCAL" -lt 1 ]; then
  echo "ERROR: empty sample_ids.txt"; exit 1
fi
echo "sample_n=$N_LOCAL (hard crop from ${SRC_PREFIX})"

STAGE="data/qa/_${PREFIX}_stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/code" "$STAGE/posters" "$STAGE/qa"

cp -f pilot_ocr_models.py "$STAGE/code/pilot_ocr_models.py"
cp -f ocr_metrics.py "$STAGE/code/ocr_metrics.py"
cp -f crop_posters_text_det.py "$STAGE/code/crop_posters_text_det.py"
cp -f aws/ocr_qwen_hard_crop_chain.sh "$STAGE/code/ocr_qwen_hard_crop_chain.sh"
cp -f aws/ocr_qwen_hard_crop_userdata.sh "$STAGE/code/ocr_qwen_hard_crop_userdata.sh"

# Stage posters via same priority chain as hard (homolog > original_up > original > w342)
export PREFIX BUCKET MAX_N
# Temporarily point staging helper at this PREFIX (reads sample_ids from data/qa/$PREFIX)
python3 aws/_stage_ocr_qwen_hard_posters.py

cp -f "data/qa/${PREFIX}/sample_ids.txt" "$STAGE/qa/sample_ids.txt"
[ -f "data/qa/${PREFIX}/sample_meta.csv" ] && \
  cp -f "data/qa/${PREFIX}/sample_meta.csv" "$STAGE/qa/sample_meta.csv"
[ -f "data/qa/${PREFIX}/poster_sources.csv" ] && \
  cp -f "data/qa/${PREFIX}/poster_sources.csv" "$STAGE/qa/poster_sources.csv"

N_LOCAL=$(wc -l < "data/qa/${PREFIX}/sample_ids.txt" | tr -d ' ')
echo "final sample_n=$N_LOCAL"
echo "jpg count: $(ls "$STAGE/posters"/*.jpg 2>/dev/null | wc -l | tr -d ' ')"

echo "--- upload code + ids + subset posters.csv ---"
aws s3 cp "$STAGE/code/pilot_ocr_models.py" "s3://${BUCKET}/${PREFIX}/code/pilot_ocr_models.py"
aws s3 cp "$STAGE/code/ocr_metrics.py" "s3://${BUCKET}/${PREFIX}/code/ocr_metrics.py"
aws s3 cp "$STAGE/code/crop_posters_text_det.py" "s3://${BUCKET}/${PREFIX}/code/crop_posters_text_det.py"
aws s3 cp "$STAGE/code/ocr_qwen_hard_crop_chain.sh" "s3://${BUCKET}/${PREFIX}/code/ocr_qwen_hard_crop_chain.sh"
aws s3 cp "$STAGE/code/ocr_qwen_hard_crop_userdata.sh" "s3://${BUCKET}/${PREFIX}/code/ocr_qwen_hard_crop_userdata.sh"
aws s3 cp "$STAGE/qa/sample_ids.txt" "s3://${BUCKET}/${PREFIX}/sample_ids.txt"
aws s3 cp "$STAGE/posters.csv" "s3://${BUCKET}/${PREFIX}/posters.csv"
[ -f "$STAGE/qa/sample_meta.csv" ] && aws s3 cp "$STAGE/qa/sample_meta.csv" "s3://${BUCKET}/${PREFIX}/sample_meta.csv"
[ -f "$STAGE/qa/poster_sources.csv" ] && aws s3 cp "$STAGE/qa/poster_sources.csv" "s3://${BUCKET}/${PREFIX}/poster_sources.csv"

MODELS="${MODELS:-qwen,qwen7}"
printf '%s\n' "$MODELS" | aws s3 cp - "s3://${BUCKET}/${PREFIX}/MODELS"
echo "staged MODELS=$MODELS"

echo "--- sync sampled posters only ---"
aws s3 sync "$STAGE/posters/" "s3://${BUCKET}/${PREFIX}/posters/" --size-only

echo "LISTO — s3://${BUCKET}/${PREFIX}/"
echo "Siguiente: MODELS=qwen,qwen7 bash aws/launch_ocr_qwen_hard_crop.sh"
