#!/bin/bash
# Pull OCR pilot results from S3 to local data/qa/ocr_pilot/.
# Usage:
#   bash pipeline/aws/pull_ocr_pilot.sh          # wait for DONE then pull
#   bash pipeline/aws/pull_ocr_pilot.sh --now    # pull whatever is there
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa/ocr_pilot

WAIT=1
for a in "$@"; do
  [ "$a" = "--now" ] && WAIT=0
done

if [ "$WAIT" = "1" ]; then
  echo "waiting for s3://$BUCKET/ocr_pilot/results/DONE ..."
  while ! aws s3 ls "s3://$BUCKET/ocr_pilot/results/DONE" >/dev/null 2>&1; do
    sleep 60
    echo "  still waiting $(date -u +%H:%M:%S)"
  done
fi

aws s3 sync "s3://${BUCKET}/ocr_pilot/results/" data/qa/ocr_pilot/

if [ -f data/qa/ocr_pilot/results.csv ]; then
  python3 - <<'PY'
import pandas as pd
from pathlib import Path
p = Path("data/qa/ocr_pilot/results.csv")
df = pd.read_csv(p)
print(f"results rows={len(df)} models={sorted(df.model.unique())}")
print(df.groupby("model").agg(
    n=("id", "count"),
    ok=("status", lambda s: (s == "ok").sum()),
    mean_overlap=("title_overlap_score", "mean"),
    mean_lat=("latency_s", "mean"),
).round(3).to_string())
print("sample:")
print(df.head(8).to_string(index=False))
PY
else
  echo "WARNING: results.csv not present yet"
  ls -la data/qa/ocr_pilot/ | head -40
fi

echo "LISTO — data/qa/ocr_pilot/"
