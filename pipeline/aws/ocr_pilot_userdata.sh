#!/bin/bash
# cloud-init: pull OCR pilot code + sample from S3, run chain, upload, shutdown.
exec > >(tee /home/ubuntu/ocr_pilot_userdata.log) 2>&1
set -euo pipefail
export BUCKET=aof-owlv2-102516364259
export AWS_DEFAULT_REGION=us-east-1
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH

echo "=== ocr_pilot userdata start $(date -u) ==="
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
mkdir -p "$PIPE/data/posters" "$PIPE/aws" "$PIPE/data/qa/ocr_pilot"

for i in $(seq 1 30); do
  if aws sts get-caller-identity >/dev/null 2>&1; then break; fi
  sleep 2
done

echo "--- pull code ---"
aws s3 cp "s3://${BUCKET}/ocr_pilot/code/pilot_ocr_models.py" "$PIPE/pilot_ocr_models.py"
aws s3 cp "s3://${BUCKET}/ocr_pilot/code/ocr_pilot_chain.sh" "$PIPE/aws/ocr_pilot_chain.sh"
chmod +x "$PIPE/aws/ocr_pilot_chain.sh"

# sample ids + posters.csv subset (jpgs synced inside chain)
aws s3 cp "s3://${BUCKET}/ocr_pilot/sample_ids.txt" "$PIPE/data/qa/ocr_pilot/sample_ids.txt"
aws s3 cp "s3://${BUCKET}/ocr_pilot/posters.csv" "$PIPE/data/posters.csv"

chown -R ubuntu:ubuntu "$ROOT"
sudo -u ubuntu -H bash -lc "cd $PIPE && bash aws/ocr_pilot_chain.sh"
