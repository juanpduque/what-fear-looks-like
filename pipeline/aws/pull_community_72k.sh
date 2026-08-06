#!/bin/bash
# Pull community-72k results from S3 (CSVs/JSON only — NOT posters by default).
# User asked not to pull yet; script is ready for later.
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/pull_community_72k.sh
#   PULL_POSTERS=1 bash pipeline/aws/pull_community_72k.sh   # optional, large
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy || true

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-community-72k}"
PULL_POSTERS="${PULL_POSTERS:-0}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
OUT=data/qa/community_72k/pull
mkdir -p "$OUT" data/community

echo "=== pull_community_72k from s3://${BUCKET}/${PREFIX}/ ==="
aws s3 sync "s3://${BUCKET}/${PREFIX}/results/" "$OUT/results/" --exclude "posters/*"
# Convenience copies
[ -f "$OUT/results/tmdb_horror_ids.csv" ] && \
  cp -f "$OUT/results/tmdb_horror_ids.csv" data/community/tmdb_horror_ids.csv || true
[ -f "$OUT/results/rekognition_community_72k.csv" ] && \
  cp -f "$OUT/results/rekognition_community_72k.csv" data/qa/rekognition_community_72k.csv || true
[ -f "$OUT/results/detecttext_community_72k.csv" ] && \
  cp -f "$OUT/results/detecttext_community_72k.csv" data/qa/detecttext_community_72k.csv || true
[ -f "$OUT/results/PROGRESS.json" ] && \
  cp -f "$OUT/results/PROGRESS.json" data/qa/community_72k/PROGRESS.json || true

if [ "$PULL_POSTERS" = "1" ]; then
  echo "--- pulling posters (large) ---"
  mkdir -p data/posters
  aws s3 sync "s3://${BUCKET}/${PREFIX}/posters/" data/posters/ --size-only
else
  echo "(skipping posters; set PULL_POSTERS=1 to sync jpgs)"
fi

echo "LISTO → $OUT"
ls -la "$OUT/results" 2>/dev/null | head -30 || true
