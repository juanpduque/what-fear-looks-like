#!/bin/bash
# Deploy + start EasyOCR on the existing hfs-imdb-reviews EC2 (no shutdown).
# Prereq: bash pipeline/aws/stage_poster_ocr_hfs.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-horror-fear-score-102516364259}"
IID="${IID:-i-08521db70960e00dd}"
KEY="${KEY:-$HOME/.ssh/aof-owlv2.pem}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"

IP=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "=== deploy poster_ocr → $IID ($IP) bucket=$BUCKET ==="

ssh -i "$KEY" -o StrictHostKeyChecking=accept-new ubuntu@"$IP" bash -s <<REMOTE
set -euo pipefail
export BUCKET=$BUCKET
export AWS_DEFAULT_REGION=us-east-1
ROOT=/home/ubuntu/aof
PIPE=\$ROOT/pipeline
mkdir -p \$PIPE/data/posters \$PIPE/aws \$PIPE/data
aws s3 cp s3://\$BUCKET/poster_ocr/code/poster_ocr.py \$PIPE/poster_ocr.py
aws s3 cp s3://\$BUCKET/poster_ocr/code/poster_ocr_chain_shared.sh \$PIPE/aws/poster_ocr_chain_shared.sh
aws s3 cp s3://\$BUCKET/poster_ocr/posters.csv \$PIPE/data/posters.csv
chmod +x \$PIPE/aws/poster_ocr_chain_shared.sh
# resume if any
aws s3 cp s3://\$BUCKET/metrics/poster_ocr_partial.csv \$PIPE/data/poster_ocr_partial.csv 2>/dev/null || true
df -h /
echo "starting nohup chain…"
nohup bash \$PIPE/aws/poster_ocr_chain_shared.sh > \$PIPE/data/poster_ocr_nohup.out 2>&1 &
echo \$! > \$PIPE/data/poster_ocr.pid
sleep 2
head -20 \$PIPE/data/poster_ocr_nohup.out || true
ps -p \$(cat \$PIPE/data/poster_ocr.pid) -o pid,cmd || true
REMOTE

echo "$IID" > "$PIPE/data/qa/poster_ocr_ec2.iid"
echo "$IP" > "$PIPE/data/qa/poster_ocr_ec2.ip"
echo "LISTO — corriendo en $IP"
echo "Progreso: aws s3 ls s3://$BUCKET/metrics/poster_ocr_partial.csv"
echo "Pull: BUCKET=$BUCKET bash pipeline/aws/pull_poster_ocr.sh  (ajustar bucket)"
