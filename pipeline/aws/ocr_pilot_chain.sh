#!/bin/bash
# OCR model pilot on EC2 GPU: install deps, run models, sync results, DONE, halt.
# Cost control: only the staged sample (~20–40 jpgs), not the full corpus.
set -euo pipefail
export BUCKET="${BUCKET:-aof-owlv2-102516364259}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH
export HF_HOME="${HF_HOME:-/home/ubuntu/.cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
LOG=$PIPE/data/qa/ocr_pilot/ocr_pilot_aws.log
mkdir -p "$PIPE/data/posters" "$PIPE/data/qa/ocr_pilot" "$PIPE/aws"
exec > >(tee -a "$LOG") 2>&1

echo "=== ocr_pilot_chain start $(date -u) ==="
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
# Prefer recent transformers for GOT / PaddleOCR-VL / Qianfan / Qwen
$PYTHON -m pip -q install -U 'transformers>=4.51.0' accelerate pillow pandas numpy \
  sentencepiece protobuf einops torchvision || true
# DeepSeek-OCR remote code needs addict/easydict; Qwen2-VL helper for vision info
$PYTHON -m pip -q install -U addict easydict || true
$PYTHON -m pip -q install -U qwen-vl-utils || true

$PYTHON - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0),
          "vram_gb", round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1))
PY

# Pull sample assets if userdata only brought code
aws s3 cp "s3://${BUCKET}/ocr_pilot/sample_ids.txt" data/qa/ocr_pilot/sample_ids.txt
aws s3 cp "s3://${BUCKET}/ocr_pilot/posters.csv" data/posters.csv
aws s3 sync "s3://${BUCKET}/ocr_pilot/posters/" data/posters/ --size-only
# attributes optional (sample already fixed via ids-file)
aws s3 cp "s3://${BUCKET}/ocr_pilot/sample_meta.csv" data/qa/ocr_pilot/sample_meta.csv 2>/dev/null || true

N_JPG=$(ls data/posters/*.jpg 2>/dev/null | wc -l | tr -d ' ')
echo "local posters: $N_JPG"
if [ "$N_JPG" -eq 0 ]; then
  echo "ERROR: no posters downloaded"; exit 1
fi
if [ "$N_JPG" -gt 80 ]; then
  echo "ERROR: refusing to run — too many posters ($N_JPG); pilot must stay small"
  exit 1
fi

cat > /tmp/ocr_pilot_s3_put.py <<'PY'
import os, sys
from pathlib import Path
import boto3
bucket = os.environ["BUCKET"]
region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
s3 = boto3.client("s3", region_name=region)
ok = 0
for name in sys.argv[1:]:
    p = Path(name)
    if not p.exists():
        print(f"skip missing {name}")
        continue
    if p.is_dir():
        for f in p.rglob("*"):
            if f.is_file():
                key = f"ocr_pilot/results/{f.relative_to(p.parent if p.name == 'ocr_pilot' else Path('data/qa'))}"
                # normalize: upload under ocr_pilot/results/...
                rel = f.relative_to(Path("data/qa/ocr_pilot")) if "ocr_pilot" in str(f) else f.name
                key = f"ocr_pilot/results/{rel}"
                s3.upload_file(str(f), bucket, key)
                print(f"uploaded s3://{bucket}/{key}")
                ok += 1
        continue
    # single file → ocr_pilot/results/<name>
    key = f"ocr_pilot/results/{p.name}"
    s3.upload_file(str(p), bucket, key)
    print(f"uploaded s3://{bucket}/{key} ({p.stat().st_size} bytes)")
    ok += 1
print(f"uploaded_count={ok}")
PY

sync_results() {
  $PYTHON /tmp/ocr_pilot_s3_put.py \
    data/qa/ocr_pilot/results.csv \
    data/qa/ocr_pilot/ocr_pilot_aws.log \
    2>/dev/null || true
  # sync per-model txt dirs
  if [ -d data/qa/ocr_pilot ]; then
    aws s3 sync data/qa/ocr_pilot/ "s3://${BUCKET}/ocr_pilot/results/" \
      --exclude "*" --include "*.csv" --include "*.txt" --include "*.log" --include "DONE" || true
  fi
}

echo "--- verify S3 write ---"
echo "S3_WRITE_OK_$(date -u +%Y%m%dT%H%M%SZ)" > data/qa/ocr_pilot/OCR_PILOT_S3_PROBE
aws s3 cp data/qa/ocr_pilot/OCR_PILOT_S3_PROBE "s3://${BUCKET}/ocr_pilot/results/OCR_PILOT_S3_PROBE"
echo "S3 write OK"

# Optional MODELS file staged for subset retries (e.g. deepseek,paddle,qwen)
if [ -z "${MODELS:-}" ]; then
  aws s3 cp "s3://${BUCKET}/ocr_pilot/MODELS" /tmp/ocr_pilot_MODELS 2>/dev/null || true
  if [ -f /tmp/ocr_pilot_MODELS ]; then
    MODELS=$(tr -d '[:space:]' </tmp/ocr_pilot_MODELS)
    echo "MODELS from S3: $MODELS"
  fi
fi
MODELS="${MODELS:-got,deepseek,paddle,qianfan,qwen}"
N="${N:-20}"
echo "MODELS=$MODELS N=$N"

# Seed prior results so --append-results can keep got/qianfan on subset retries
aws s3 cp "s3://${BUCKET}/ocr_pilot/results/results.csv" \
  data/qa/ocr_pilot/results.csv 2>/dev/null || true
# clear stale DONE so monitors wait for this run
aws s3 rm "s3://${BUCKET}/ocr_pilot/results/DONE" 2>/dev/null || true
rm -f data/qa/ocr_pilot/DONE

# Run models one-by-one so a crash/OOM still leaves prior results on S3
IFS=',' read -ra MODEL_ARR <<< "$MODELS"
for m in "${MODEL_ARR[@]}"; do
  m=$(echo "$m" | tr -d ' ')
  [ -z "$m" ] && continue
  echo "--- run model=$m $(date -u) ---"
  # DeepSeek remote code requires transformers==4.46.3 (official HF). Pin only for
  # that model, then restore >=4.51 for paddle/qwen/got/qianfan.
  if [ "$m" = "deepseek" ]; then
    echo "pinning transformers==4.46.3 for DeepSeek-OCR (official HF requirement)"
    $PYTHON -m pip -q install 'transformers==4.46.3' 'tokenizers==0.20.3' || true
  fi
  set +e
  $PYTHON -u pilot_ocr_models.py \
    --n "$N" \
    --ids-file data/qa/ocr_pilot/sample_ids.txt \
    --models "$m" \
    --append-results
  rc=$?
  set -e
  if [ "$m" = "deepseek" ]; then
    echo "restoring transformers>=4.51.0 after deepseek"
    $PYTHON -m pip -q install -U 'transformers>=4.51.0' || true
  fi
  echo "model=$m exit=$rc"
  sync_results
  echo "[checkpoint] synced after $m"
done

date -u +"OCR_PILOT_DONE_%Y%m%dT%H%M%SZ" > data/qa/ocr_pilot/DONE
aws s3 cp data/qa/ocr_pilot/DONE "s3://${BUCKET}/ocr_pilot/results/DONE"
sync_results
echo "=== ocr_pilot_chain done $(date -u) ==="
sleep 15
sudo shutdown -h now
