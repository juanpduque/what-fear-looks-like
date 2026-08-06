#!/bin/bash
# cloud-init: pull hard-crop Qwen OCR code + sample from S3, run chain, upload, shutdown.
exec > >(tee /home/ubuntu/ocr_qwen_hard_crop_userdata.log) 2>&1
set -euo pipefail
export BUCKET=aof-owlv2-102516364259
export PREFIX=ocr_qwen_hard_crop
export AWS_DEFAULT_REGION=us-east-1
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH

echo "=== ${PREFIX} userdata start $(date -u) ==="
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
mkdir -p "$PIPE/data/posters_hard" "$PIPE/aws" "$PIPE/data/qa/${PREFIX}"

for i in $(seq 1 30); do
  if aws sts get-caller-identity >/dev/null 2>&1; then break; fi
  sleep 2
done

echo "--- pull code ---"
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/pilot_ocr_models.py" "$PIPE/pilot_ocr_models.py"
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/ocr_metrics.py" "$PIPE/ocr_metrics.py"
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/crop_posters_text_det.py" "$PIPE/crop_posters_text_det.py"
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/ocr_qwen_hard_crop_chain.sh" "$PIPE/aws/ocr_qwen_hard_crop_chain.sh"
chmod +x "$PIPE/aws/ocr_qwen_hard_crop_chain.sh"

aws s3 cp "s3://${BUCKET}/${PREFIX}/sample_ids.txt" "$PIPE/data/qa/${PREFIX}/sample_ids.txt"
aws s3 cp "s3://${BUCKET}/${PREFIX}/posters.csv" "$PIPE/data/posters.csv"

chown -R ubuntu:ubuntu "$ROOT"
sudo -u ubuntu -H bash -lc "cd $PIPE && bash aws/ocr_qwen_hard_crop_chain.sh"
