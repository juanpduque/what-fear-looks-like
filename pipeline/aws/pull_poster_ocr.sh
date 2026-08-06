#!/bin/bash
# Pull EasyOCR full-text results after AWS poster_ocr job finishes.
# Usage: bash pipeline/aws/pull_poster_ocr.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

echo "waiting for s3://$BUCKET/metrics/POSTER_OCR_DONE ..."
while ! aws s3 ls "s3://$BUCKET/metrics/POSTER_OCR_DONE" >/dev/null 2>&1; do
  sleep 60
  echo "  still waiting $(date -u +%H:%M:%S)"
done
aws s3 cp "s3://$BUCKET/metrics/POSTER_OCR_DONE" data/POSTER_OCR_DONE
aws s3 cp "s3://$BUCKET/metrics/poster_ocr.csv" data/poster_ocr.csv
aws s3 cp "s3://$BUCKET/metrics/poster_ocr_partial.csv" data/poster_ocr_partial.csv || true
aws s3 cp "s3://$BUCKET/metrics/poster_ocr_aws.log" data/poster_ocr_aws.log || true

python3 - <<'PY'
import pandas as pd
from pathlib import Path
DATA = Path("data")
p = set(pd.read_csv(DATA / "posters.csv", usecols=["id"]).id.astype(int))
o = pd.read_csv(DATA / "poster_ocr.csv")
oids = set(o.id.astype(int))
ok = (o.error.fillna("") == "") & (o.full_ocr.fillna("").str.len() > 0)
print(f"poster_ocr {len(o):,} corpus_miss={len(p - oids):,} with_text={int(ok.sum()):,}")
print(o.error.fillna("(ok)").value_counts().head(10).to_string())
print("sample:")
print(o.loc[ok, ["id", "n_lines", "mean_conf", "full_ocr"]].head(5).to_string(index=False))
PY

echo "LISTO — data/poster_ocr.csv"
