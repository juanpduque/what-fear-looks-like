#!/bin/bash
# cloud-init: pull seg_drift payload from S3 and run GPU segmentation chain
exec > >(tee /home/ubuntu/seg_drift_userdata.log) 2>&1
set -euo pipefail
export BUCKET=aof-owlv2-102516364259
export AWS_DEFAULT_REGION=us-east-1
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH

echo "=== userdata start $(date -u) ==="
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
mkdir -p "$PIPE/data/posters" "$PIPE/aws" "$PIPE/data"

# wait for IAM role credentials
for i in $(seq 1 30); do
  if aws sts get-caller-identity >/dev/null 2>&1; then break; fi
  sleep 2
done

echo "--- sync posters ---"
aws s3 sync "s3://${BUCKET}/seg_drift/posters/" "$PIPE/data/posters/"
aws s3 cp "s3://${BUCKET}/seg_drift/posters.csv" "$PIPE/data/posters.csv"
aws s3 cp "s3://${BUCKET}/seg_drift/segmentation.csv" "$PIPE/data/segmentation.csv"
aws s3 cp "s3://${BUCKET}/seg_drift/segmentation_partial.csv" "$PIPE/data/segmentation_partial.csv" || true
aws s3 cp "s3://${BUCKET}/seg_drift/code/segmentation.py" "$PIPE/segmentation.py"
aws s3 cp "s3://${BUCKET}/seg_drift/code/seg_drift_chain.sh" "$PIPE/aws/seg_drift_chain.sh"
chmod +x "$PIPE/aws/seg_drift_chain.sh"

chown -R ubuntu:ubuntu "$ROOT"
echo "jpg count: $(ls "$PIPE/data/posters"/*.jpg 2>/dev/null | wc -l)"

# run as ubuntu so logs land in the right home
sudo -u ubuntu -H bash -lc "cd $PIPE && bash aws/seg_drift_chain.sh"
