#!/bin/bash
# Finish segmentation (SegFormer + Minc + CLIP patches) for missing posters, upload, halt.
set -euo pipefail
export PATH=/opt/pytorch/bin:$PATH
export BUCKET=aof-owlv2-102516364259
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
LOG=$PIPE/data/segmentation_aws.log
mkdir -p "$PIPE/data/posters"
exec > >(tee -a "$LOG") 2>&1

echo "=== seg_chain start $(date -u) ==="
cd "$PIPE"
echo "device check:"; python -c "import torch; print('cuda', torch.cuda.is_available())"

python -m pip -q install -U transformers open_clip_torch pandas pillow numpy opencv-python-headless

# Seed checkpoint from published sample so we only process missing ids
if [ -f data/segmentation.csv ] && [ ! -f data/segmentation_partial.csv ]; then
  cp data/segmentation.csv data/segmentation_partial.csv
fi
# Prefer published over stale partial if published has more unique ids
python - <<'PY'
import pandas as pd
from pathlib import Path
DATA=Path('data')
final, part = DATA/'segmentation.csv', DATA/'segmentation_partial.csv'
if final.exists():
    f=pd.read_csv(final); f['id']=f['id'].astype(int)
    if part.exists():
        p=pd.read_csv(part); p['id']=p['id'].astype(int)
        if f['id'].nunique() >= p['id'].nunique():
            # keep union
            m=pd.concat([p,f]).drop_duplicates('id', keep='last')
            m.to_csv(part, index=False)
            print('seeded partial union', len(m))
        else:
            print('keeping larger partial', p['id'].nunique())
    else:
        f.to_csv(part, index=False)
        print('seeded partial from csv', len(f))
PY

echo "--- segmentation ---"
python -u segmentation.py

echo "--- upload ---"
for f in segmentation.csv segmentation_partial.csv segmentation_decade.json segmentation_aws.log; do
  [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/metrics/$f"
done
date -u +"SEG_DONE_%Y%m%dT%H%M%SZ" > data/SEG_DONE
aws s3 cp data/SEG_DONE "s3://${BUCKET}/metrics/SEG_DONE"
echo "=== seg_chain done $(date -u) ==="
sleep 20
sudo shutdown -h now
