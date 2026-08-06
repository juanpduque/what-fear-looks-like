#!/bin/bash
# Pull Qwen-homolog OCR results from S3; optionally terminate leftover EC2.
#
#   bash aws/pull_ocr_qwen_homolog.sh          # wait for DONE then pull
#   bash aws/pull_ocr_qwen_homolog.sh --now    # pull whatever is there
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_qwen_homolog}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p "data/qa/${PREFIX}"

WAIT=1
for a in "$@"; do
  [ "$a" = "--now" ] && WAIT=0
done

if [ "$WAIT" = "1" ]; then
  echo "waiting for s3://$BUCKET/${PREFIX}/results/DONE ..."
  while ! aws s3 ls "s3://$BUCKET/${PREFIX}/results/DONE" >/dev/null 2>&1; do
    sleep 60
    echo "  still waiting $(date -u +%H:%M:%S)"
  done
fi

aws s3 sync "s3://${BUCKET}/${PREFIX}/results/" "data/qa/${PREFIX}/"

if [ -f "data/qa/${PREFIX}/results.csv" ]; then
  python3 - <<PY
import pandas as pd
from pathlib import Path
p = Path("data/qa/${PREFIX}/results.csv")
df = pd.read_csv(p)
print(f"results rows={len(df)} models={sorted(df.model.unique())}")
print(df.groupby("model").agg(
    n=("id", "count"),
    ok=("status", lambda s: (s == "ok").sum()),
    mean_overlap=("title_overlap_score", "mean"),
    mean_lat=("latency_s", "mean"),
).round(3).to_string())
PY
else
  echo "WARNING: results.csv not present yet"
  ls -la "data/qa/${PREFIX}/" | head -40
fi

IID_FILE="data/qa/${PREFIX}_ec2.iid"
if [ -f "$IID_FILE" ]; then
  IID=$(tr -d '[:space:]' < "$IID_FILE")
  STATE=$(aws ec2 describe-instances --instance-ids "$IID" \
    --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || echo none)
  echo "ec2 $IID state=$STATE"
  if [ "$STATE" = "running" ] || [ "$STATE" = "pending" ] || [ "$STATE" = "stopping" ]; then
    echo "terminating leftover instance $IID"
    aws ec2 terminate-instances --instance-ids "$IID" >/dev/null
  fi
fi

echo "LISTO — data/qa/${PREFIX}/"
