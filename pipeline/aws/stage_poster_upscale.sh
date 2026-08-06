#!/bin/bash
# Stage Real-ESRGAN upscale inputs to S3.
#   bash aws/stage_poster_upscale.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-poster_upscale}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

IDS=data/qa/posters_upscale_ids.txt
if [ ! -f "$IDS" ]; then
  echo "missing $IDS — build it first"; exit 1
fi

mkdir -p weights
WEIGHTS=weights/RealESRGAN_x2plus.pth
if [ ! -f "$WEIGHTS" ]; then
  echo "downloading RealESRGAN_x2plus.pth…"
  curl -L --fail -o "$WEIGHTS" \
    https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth
fi

echo "=== stage ${PREFIX} ==="
aws s3 cp upscale_posters_realesrgan.py "s3://${BUCKET}/${PREFIX}/code/upscale_posters_realesrgan.py"
aws s3 cp aws/poster_upscale_chain.sh "s3://${BUCKET}/${PREFIX}/code/poster_upscale_chain.sh"
aws s3 cp aws/poster_upscale_userdata.sh "s3://${BUCKET}/${PREFIX}/code/poster_upscale_userdata.sh"
aws s3 cp "$IDS" "s3://${BUCKET}/${PREFIX}/posters_upscale_ids.txt"
aws s3 cp data/qa/posters_upscale_ids_meta.csv "s3://${BUCKET}/${PREFIX}/posters_upscale_ids_meta.csv" 2>/dev/null || true
aws s3 cp "$WEIGHTS" "s3://${BUCKET}/${PREFIX}/weights/RealESRGAN_x2plus.pth"
N=$(wc -l < "$IDS" | tr -d ' ')
echo "LISTO — staged n=$N ids + weights → s3://${BUCKET}/${PREFIX}/"
echo "Next: bash aws/launch_poster_upscale.sh"
