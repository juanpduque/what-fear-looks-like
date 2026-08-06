#!/bin/bash
# Wait for Real-ESRGAN DONE on S3, sync upscaled, letterbox 1000×1500, upload homolog.
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-poster_upscale}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
LOG=data/qa/posters_homolog_run.log
mkdir -p data/qa data/posters_original_up data/posters_homolog

exec >>"$LOG" 2>&1
echo "=== wait_homolog start $(date -u) ==="

echo "waiting for s3://${BUCKET}/${PREFIX}/results/DONE …"
while true; do
  if aws s3 ls "s3://${BUCKET}/${PREFIX}/results/DONE" >/dev/null 2>&1; then
    echo "DONE found $(date -u)"
    aws s3 cp "s3://${BUCKET}/${PREFIX}/results/DONE" data/qa/poster_upscale_DONE.txt || true
    cat data/qa/poster_upscale_DONE.txt || true
    break
  fi
  # also stop waiting if instance gone AND some ups already synced? keep polling DONE only
  sleep 60
done

echo "--- sync upscaled ---"
aws s3 sync "s3://${BUCKET}/posters_original_up/" data/posters_original_up/ --size-only
echo "up local: $(ls data/posters_original_up/*.jpg 2>/dev/null | wc -l | tr -d ' ')"

echo "--- letterbox 1000x1500 ---"
python3 -u homolog_posters_letterbox.py --width 1000 --height 1500 --workers 8

echo "--- upload homolog ---"
aws s3 sync data/posters_homolog/ "s3://${BUCKET}/posters_homolog/" --size-only
aws s3 cp data/qa/posters_homolog_manifest.csv \
  "s3://${BUCKET}/posters_homolog/posters_homolog_manifest.csv"
date -u > data/qa/posters_homolog_DONE
echo "canvas=1000x1500 letterbox" >> data/qa/posters_homolog_DONE
aws s3 cp data/qa/posters_homolog_DONE "s3://${BUCKET}/posters_homolog/DONE"

echo "=== wait_homolog done $(date -u) ==="
