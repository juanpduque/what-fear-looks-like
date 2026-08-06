#!/bin/bash
# cloud-init: pull OCR code (+ posters.csv) from S3; stream jpgs at runtime
exec > >(tee /home/ubuntu/poster_ocr_userdata.log) 2>&1
set -euo pipefail
export BUCKET=aof-owlv2-102516364259
export AWS_DEFAULT_REGION=us-east-1
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH

echo "=== poster_ocr userdata start $(date -u) ==="
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
mkdir -p "$PIPE/data/posters" "$PIPE/aws" "$PIPE/data"

for i in $(seq 1 30); do
  if aws sts get-caller-identity >/dev/null 2>&1; then break; fi
  sleep 2
done

echo "--- pull code ---"
aws s3 cp "s3://${BUCKET}/poster_ocr/code/poster_ocr.py" "$PIPE/poster_ocr.py"
aws s3 cp "s3://${BUCKET}/poster_ocr/code/poster_ocr_chain.sh" "$PIPE/aws/poster_ocr_chain.sh"
aws s3 cp "s3://${BUCKET}/poster_ocr/posters.csv" "$PIPE/data/posters.csv"
chmod +x "$PIPE/aws/poster_ocr_chain.sh"
aws s3 cp "s3://${BUCKET}/metrics/poster_ocr_partial.csv" "$PIPE/data/poster_ocr_partial.csv" 2>/dev/null || true

chown -R ubuntu:ubuntu "$ROOT"
sudo -u ubuntu -H bash -lc "cd $PIPE && bash aws/poster_ocr_chain.sh"
