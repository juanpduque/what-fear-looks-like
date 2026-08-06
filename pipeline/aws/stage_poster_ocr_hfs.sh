#!/bin/bash
# Stage posters for OCR on the shared hfs EC2 (IAM → horror-fear-score bucket).
# Usage: bash pipeline/aws/stage_poster_ocr_hfs.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-horror-fear-score-102516364259}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

echo "=== stage → s3://$BUCKET/poster_ocr/ ==="
aws s3 cp poster_ocr.py "s3://${BUCKET}/poster_ocr/code/poster_ocr.py"
aws s3 cp aws/poster_ocr_chain_shared.sh "s3://${BUCKET}/poster_ocr/code/poster_ocr_chain_shared.sh"
aws s3 cp data/posters.csv "s3://${BUCKET}/poster_ocr/posters.csv"

echo "--- sync posters (size-only; ~2–3 GB) ---"
# Only corpus ids that exist locally
python3 - <<'PY'
import os
from pathlib import Path
import pandas as pd
data = Path("data")
ids = set(pd.read_csv(data/"posters.csv", usecols=["id"]).id.astype(int))
src = data/"posters"
# write a manifest of relative paths for aws s3 sync include? easier: sync whole dir filtered
n = sum(1 for p in src.glob("*.jpg") if int(p.stem) in ids)
print(f"local corpus jpgs available: {n:,}")
PY
aws s3 sync data/posters/ "s3://${BUCKET}/poster_ocr/posters/" --size-only \
  --exclude "*" --include "*.jpg"

echo "LISTO — s3://$BUCKET/poster_ocr/"
