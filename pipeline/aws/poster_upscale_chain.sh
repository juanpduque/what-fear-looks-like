#!/bin/bash
# EC2 chain: Real-ESRGAN x2 on posters with width<1000 from S3 originals.
set -euo pipefail
export BUCKET="${BUCKET:-aof-owlv2-102516364259}"
export PREFIX="${PREFIX:-poster_upscale}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
LOG=$PIPE/data/qa/${PREFIX}/${PREFIX}_aws.log
mkdir -p "$PIPE/data/posters_original" "$PIPE/data/posters_original_up" \
  "$PIPE/data/qa/${PREFIX}" "$PIPE/weights" "$PIPE/aws"
exec > >(tee -a "$LOG") 2>&1

echo "=== ${PREFIX}_chain start $(date -u) ==="
cd "$PIPE"

for cand in /opt/pytorch/bin /home/ubuntu/pytorch/bin; do
  if [ -x "$cand/python" ]; then
    export PATH="$cand:$PATH"
    echo "using python from $cand"
    break
  fi
done

PYTHON="${PYTHON:-python3}"
$PYTHON -m pip -q install -U pip
$PYTHON -m pip -q install -U opencv-python-headless pillow numpy spandrel || true

$PYTHON - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0),
          "vram_gb", round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1))
from spandrel import ModelLoader
print("spandrel OK")
PY

# Pull code + id list
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/upscale_posters_realesrgan.py" upscale_posters_realesrgan.py
aws s3 cp "s3://${BUCKET}/${PREFIX}/posters_upscale_ids.txt" data/qa/posters_upscale_ids.txt

WEIGHTS=weights/RealESRGAN_x2plus.pth
if [ ! -f "$WEIGHTS" ]; then
  echo "--- download RealESRGAN_x2plus weights ---"
  aws s3 cp "s3://${BUCKET}/${PREFIX}/weights/RealESRGAN_x2plus.pth" "$WEIGHTS" 2>/dev/null \
    || wget -q -O "$WEIGHTS" \
      https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth
fi
ls -lh "$WEIGHTS"

echo "--- pull input posters ---"
# Full sync is faster/more reliable than 5.7k individual cps (~5.5 GB).
aws s3 sync "s3://${BUCKET}/posters_original/" data/posters_original/ --size-only
N_IN=$(ls data/posters_original/*.jpg 2>/dev/null | wc -l)
echo "local inputs: $N_IN"

# Resume: pull any already-upscaled from S3
aws s3 sync "s3://${BUCKET}/posters_original_up/" data/posters_original_up/ --size-only || true
aws s3 cp "s3://${BUCKET}/${PREFIX}/results/posters_upscale_progress.csv" \
  data/qa/posters_upscale_progress.csv 2>/dev/null || true

sync_out() {
  aws s3 sync data/posters_original_up/ "s3://${BUCKET}/posters_original_up/" --size-only
  aws s3 cp data/qa/posters_upscale_progress.csv \
    "s3://${BUCKET}/${PREFIX}/results/posters_upscale_progress.csv" 2>/dev/null || true
  aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/${PREFIX}_aws.log" 2>/dev/null || true
}

echo "--- Real-ESRGAN ---"
$PYTHON -u upscale_posters_realesrgan.py \
  --ids-file data/qa/posters_upscale_ids.txt \
  --in-dir data/posters_original \
  --out-dir data/posters_original_up \
  --weights "$WEIGHTS" \
  --outscale 2 \
  --tile 400 \
  --min-width 1000 \
  --progress-every 25

sync_out

N_OUT=$(ls data/posters_original_up/*.jpg 2>/dev/null | wc -l)
echo "upscaled outputs: $N_OUT"
date -u > data/qa/${PREFIX}/DONE
echo "n_out=$N_OUT" >> data/qa/${PREFIX}/DONE
aws s3 cp "data/qa/${PREFIX}/DONE" "s3://${BUCKET}/${PREFIX}/results/DONE"
sync_out

echo "=== ${PREFIX}_chain done $(date -u) ==="
sudo shutdown -h now || sudo poweroff || true
