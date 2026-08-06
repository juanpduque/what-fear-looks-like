#!/bin/bash
# Pull OCR results from horror-fear-score bucket (shared EC2 job).
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-horror-fear-score-102516364259}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

echo "waiting for s3://$BUCKET/metrics/POSTER_OCR_DONE ..."
while ! aws s3 ls "s3://$BUCKET/metrics/POSTER_OCR_DONE" >/dev/null 2>&1; do
  sleep 60
  echo "  still waiting $(date -u +%H:%M:%S)"
  aws s3 ls "s3://$BUCKET/metrics/poster_ocr_partial.csv" 2>/dev/null || true
done
aws s3 cp "s3://$BUCKET/metrics/POSTER_OCR_DONE" data/POSTER_OCR_DONE
aws s3 cp "s3://$BUCKET/metrics/poster_ocr.csv" data/poster_ocr.csv
aws s3 cp "s3://$BUCKET/metrics/poster_ocr_partial.csv" data/poster_ocr_partial.csv || true
aws s3 cp "s3://$BUCKET/metrics/poster_ocr_aws.log" data/poster_ocr_aws.log || true
wc -l data/poster_ocr.csv
echo "LISTO — data/poster_ocr.csv"
