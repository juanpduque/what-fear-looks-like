#!/bin/bash
# Pull IMDb Selenium results from workshop S3 → pipeline/data/
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/pull_imdb_selenium.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-imdb-selenium}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa data/imdb_selenium_s3_pull

echo "=== pull imdb_selenium from s3://${BUCKET}/${PREFIX}/results/ ==="
aws s3 sync "s3://${BUCKET}/${PREFIX}/results/" data/imdb_selenium_s3_pull/ --exact-timestamps

# Promote main CSVs into data/ if present
for f in \
  imdb_selenium_features_hits.csv \
  imdb_selenium_features_miss.csv \
  imdb_selenium_features_run.log \
  imdb_basics_ambiguous_selenium_hits.csv \
  imdb_basics_ambiguous_selenium_miss.csv \
  imdb_basics_ambiguous_selenium_run.log \
  imdb_ids.csv \
  IMDB_SELENIUM_DONE
do
  if [ -f "data/imdb_selenium_s3_pull/$f" ]; then
    cp -f "data/imdb_selenium_s3_pull/$f" "data/$f"
    echo "  → data/$f"
  fi
done

echo "LISTO"
ls -lah data/imdb_selenium_s3_pull | head -30
[ -f data/IMDB_SELENIUM_DONE ] && cat data/IMDB_SELENIUM_DONE || echo "(no DONE marker yet)"
