#!/bin/bash
# Pull segmentation results after AWS seg_drift job finishes.
# Usage: bash pipeline/aws/pull_seg_drift.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

echo "waiting for s3://$BUCKET/metrics/SEG_DONE ..."
while ! aws s3 ls "s3://$BUCKET/metrics/SEG_DONE" >/dev/null 2>&1; do
  sleep 60
  echo "  still waiting $(date -u +%H:%M:%S)"
done
aws s3 cp "s3://$BUCKET/metrics/SEG_DONE" data/SEG_DONE
aws s3 cp "s3://$BUCKET/metrics/segmentation.csv" data/segmentation.csv
aws s3 cp "s3://$BUCKET/metrics/segmentation_partial.csv" data/segmentation_partial.csv || true
aws s3 cp "s3://$BUCKET/metrics/segmentation_decade.json" data/segmentation_decade.json || true
aws s3 cp "s3://$BUCKET/metrics/segmentation_aws.log" data/segmentation_aws.log || true

# Landscape/non-poster exclusions may post-date the EC2 seed — re-apply.
python3 apply_exclusions.py

python3 - <<'PY'
import pandas as pd
from pathlib import Path
DATA=Path('data')
p=set(pd.read_csv(DATA/'posters.csv', usecols=['id']).id.astype(int))
s=set(pd.read_csv(DATA/'segmentation.csv', usecols=['id']).id.astype(int))
print(f'segmentation {len(s):,} miss={len(p-s):,}')
PY

python3 build_lookup.py
python3 validate_corpus.py --layers 1
echo "LISTO — corpus segmentation alineada."
