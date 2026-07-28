#!/bin/bash
# Finish segmentation for primary-drift reanalyze ids on EC2 GPU, upload, halt.
# Expects on the instance (synced from S3 by user-data):
#   pipeline/data/posters/*.jpg          (at least the pending ids)
#   pipeline/data/posters.csv
#   pipeline/data/segmentation.csv       (seed: done rows)
#   pipeline/data/segmentation_partial.csv (optional)
#   pipeline/segmentation.py + deps
set -euo pipefail
export PATH=/opt/pytorch/bin:$PATH
export BUCKET="${BUCKET:-aof-owlv2-102516364259}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
LOG=$PIPE/data/segmentation_aws.log
mkdir -p "$PIPE/data/posters"
exec > >(tee -a "$LOG") 2>&1

echo "=== seg_drift_chain start $(date -u) ==="
cd "$PIPE"
echo "device check:"; python -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"

python -m pip -q install -U transformers open_clip_torch pandas pillow numpy opencv-python-headless

# Seed / union checkpoints so we only process missing ids
python - <<'PY'
import pandas as pd
from pathlib import Path
DATA = Path("data")
final, part = DATA / "segmentation.csv", DATA / "segmentation_partial.csv"
if final.exists():
    f = pd.read_csv(final)
    f["id"] = f["id"].astype(int)
    if part.exists():
        p = pd.read_csv(part)
        p["id"] = p["id"].astype(int)
        m = pd.concat([p, f]).drop_duplicates("id", keep="last")
        m.to_csv(part, index=False)
        print("seeded partial union", len(m))
    else:
        f.to_csv(part, index=False)
        print("seeded partial from csv", len(f))
meta = pd.read_csv(DATA / "posters.csv", usecols=["id"])
print("posters.csv", len(meta))
done = set(pd.read_csv(part if part.exists() else final, usecols=["id"])["id"].astype(int))
print("pending segmentation", len(set(meta["id"].astype(int)) - done))
PY

sync_out() {
  for f in segmentation.csv segmentation_partial.csv segmentation_decade.json segmentation_aws.log; do
    [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/metrics/$f" --quiet || true
  done
}

(
  while true; do
    sleep 180
    sync_out
    echo "[checkpoint $(date -u +%H:%M:%S)] synced segmentation artifacts" || true
  done
) &
CKPID=$!

echo "--- segmentation ---"
python -u segmentation.py
sync_out

kill "$CKPID" 2>/dev/null || true

date -u +"SEG_DONE_%Y%m%dT%H%M%SZ" > data/SEG_DONE
aws s3 cp data/SEG_DONE "s3://${BUCKET}/metrics/SEG_DONE"
aws s3 cp data/segmentation_aws.log "s3://${BUCKET}/metrics/segmentation_aws.log"
echo "=== seg_drift_chain done $(date -u) ==="
sleep 20
sudo shutdown -h now
