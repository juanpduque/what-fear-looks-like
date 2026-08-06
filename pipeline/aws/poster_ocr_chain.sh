#!/bin/bash
# EasyOCR full-text on EC2 GPU: stream posters from S3, checkpoint, halt.
set -euo pipefail
export BUCKET="${BUCKET:-aof-owlv2-102516364259}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
LOG=$PIPE/data/poster_ocr_aws.log
mkdir -p "$PIPE/data/posters"
exec > >(tee -a "$LOG") 2>&1

echo "=== poster_ocr_chain start $(date -u) ==="
cd "$PIPE"

for cand in /opt/pytorch/bin /home/ubuntu/pytorch/bin; do
  if [ -x "$cand/python" ]; then
    export PATH="$cand:$PATH"
    echo "using python from $cand"
    break
  fi
done
if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
  conda activate pytorch 2>/dev/null || conda activate pytorch_p312 2>/dev/null || true
fi

PYTHON="${PYTHON:-python3}"
$PYTHON -m pip -q install -U pip
$PYTHON -m pip -q install -U easyocr opencv-python-headless pandas numpy pillow boto3
$PYTHON - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0))
PY

aws s3 cp "s3://${BUCKET}/metrics/poster_ocr_partial.csv" data/poster_ocr_partial.csv 2>/dev/null || true
aws s3 cp "s3://${BUCKET}/metrics/poster_ocr.csv" data/poster_ocr.csv 2>/dev/null || true

cat > /tmp/s3_put.py <<'PY'
import os, sys
from pathlib import Path
import boto3
bucket = os.environ["BUCKET"]
region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
s3 = boto3.client("s3", region_name=region)
ok = 0
for name in sys.argv[1:]:
    p = Path("data") / name
    if not p.exists():
        print(f"skip missing {name}")
        continue
    key = f"metrics/{name}"
    s3.upload_file(str(p), bucket, key)
    print(f"uploaded s3://{bucket}/{key} ({p.stat().st_size} bytes)")
    ok += 1
if ok == 0:
    raise SystemExit("no files uploaded")
PY

sync_out() {
  $PYTHON /tmp/s3_put.py poster_ocr.csv poster_ocr_partial.csv poster_ocr_aws.log || true
}

echo "--- verify S3 write ---"
echo "S3_WRITE_OK_$(date -u +%Y%m%dT%H%M%SZ)" > data/POSTER_OCR_S3_PROBE
$PYTHON /tmp/s3_put.py POSTER_OCR_S3_PROBE
echo "S3 write OK"

(
  while true; do
    sleep 180
    sync_out && echo "[checkpoint $(date -u +%H:%M:%S)] synced ocr csv to s3" || echo "[checkpoint FAIL $(date -u +%H:%M:%S)]"
  done
) &
CKPID=$!

GPU_FLAG=()
if $PYTHON -c "import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)"; then
  GPU_FLAG=(--gpu)
  echo "using --gpu"
else
  echo "no CUDA — CPU EasyOCR (slower)"
fi

echo "--- poster_ocr (S3 stream + unlink) ---"
$PYTHON -u poster_ocr.py --save-every 50 \
  --s3-bucket "$BUCKET" \
  --s3-prefix poster_ocr/posters \
  --unlink-after \
  "${GPU_FLAG[@]}"
sync_out

kill "$CKPID" 2>/dev/null || true

date -u +"POSTER_OCR_DONE_%Y%m%dT%H%M%SZ" > data/POSTER_OCR_DONE
$PYTHON /tmp/s3_put.py POSTER_OCR_DONE poster_ocr.csv poster_ocr_partial.csv poster_ocr_aws.log
echo "=== poster_ocr_chain done $(date -u) ==="
sleep 20
sudo shutdown -h now
