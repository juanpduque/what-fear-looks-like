#!/bin/bash
# Fix-pass: finish multi_analyze for 2023–2025 newcomers, upload, halt.
set -euo pipefail
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH
export BUCKET=aof-owlv2-102516364259
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
LOG=$PIPE/data/attrs_fix.log
mkdir -p "$PIPE/data"
exec > >(tee -a "$LOG") 2>&1

echo "=== attrs_fix start $(date -u) ==="
cd "$PIPE"

python3 -m pip -q install -U opencv-python-headless pandas numpy shapely 2>/dev/null \
  || python -m pip -q install -U opencv-python-headless pandas numpy shapely

# Prefer existing attributes.csv as checkpoint seed (already on disk from stage)
if [ -f data/attributes.csv ] && [ ! -f data/attributes_partial.csv ]; then
  cp data/attributes.csv data/attributes_partial.csv
fi

echo "--- multi_analyze ---"
python3 -u multi_analyze.py

echo "--- upload ---"
for f in attributes.csv attributes_partial.csv attributes_decade.json attrs_fix.log; do
  [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/metrics/$f"
done
date -u +"ATTRS_DONE_%Y%m%dT%H%M%SZ" > data/ATTRS_DONE
aws s3 cp data/ATTRS_DONE "s3://${BUCKET}/metrics/ATTRS_DONE"
echo "=== attrs_fix done $(date -u) ==="
sleep 15
sudo shutdown -h now
