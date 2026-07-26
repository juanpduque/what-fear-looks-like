#!/bin/bash
# After OWL finishes: extend corpus metrics for 2023–2025 newcomers, upload to S3, halt.
set -euo pipefail
export PATH=/opt/pytorch/bin:$PATH
export BUCKET=aof-owlv2-102516364259
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
LOG=$PIPE/data/metrics_chain.log
exec > >(tee -a "$LOG") 2>&1

echo "=== metrics_chain start $(date -u) ==="
cd "$PIPE"

# Ensure YuNet model
mkdir -p models
if [ ! -f models/face_detection_yunet_2023mar.onnx ]; then
  curl -fsSL -o models/face_detection_yunet_2023mar.onnx \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
fi

python -m pip -q install -U open_clip_torch scikit-learn shapely opencv-python-headless pandas pillow numpy

echo "--- color ---"
python -u analyze_color_ids.py --ids-file data/new_2023_2025_ids.csv

echo "--- clip embed ---"
python -u clip_embed.py

echo "--- faces ---"
# seed checkpoint from published faces so we only process new ids
if [ -f data/faces_v2.csv ] && [ ! -f data/faces_v2_partial.csv ]; then
  cp data/faces_v2.csv data/faces_v2_partial.csv
fi
python -u faces_v2.py

echo "--- multi_analyze ---"
python -u multi_analyze.py

echo "--- clip census / medium / typography (reuse embeddings) ---"
python -u clip_census.py || true
python -u clip_medium.py || true
python -u clip_typography_axis.py || true

echo "--- upload results ---"
for f in \
  posters.csv attributes.csv attributes_decade.json \
  faces_v2.csv faces_v2_decade.json \
  clip_embeddings.npz \
  census.csv census_decade.json \
  medium.csv typography.csv typography_decade.json \
  new_2023_2025_ids.csv metrics_chain.log \
  creature_boxes.json owlv2_full_run.log
do
  [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/metrics/$f" || true
done
[ -f ../site/data/creature_boxes.js ] && aws s3 cp ../site/data/creature_boxes.js "s3://${BUCKET}/creature_boxes.js" || true

date -u +"METRICS_DONE_%Y%m%dT%H%M%SZ" > data/METRICS_DONE
aws s3 cp data/METRICS_DONE "s3://${BUCKET}/metrics/METRICS_DONE"
echo "=== metrics_chain done $(date -u) ==="
sleep 20
sudo shutdown -h now
