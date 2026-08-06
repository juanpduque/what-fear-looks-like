#!/bin/bash
# Hard-set Qwen OCR A/B (EC2 GPU): 2B then 7B on same staged posters.
# Periodic S3 sync, DONE, halt.
set -euo pipefail
export BUCKET="${BUCKET:-aof-owlv2-102516364259}"
export PREFIX="${PREFIX:-ocr_qwen_hard}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH
export HF_HOME="${HF_HOME:-/home/ubuntu/.cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
export SYNC_SECS="${SYNC_SECS:-120}"
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
LOG=$PIPE/data/qa/${PREFIX}/${PREFIX}_aws.log
mkdir -p "$PIPE/data/posters_hard" "$PIPE/data/qa/${PREFIX}" "$PIPE/aws"
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
if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
  conda activate pytorch 2>/dev/null || conda activate pytorch_p312 2>/dev/null || true
fi

PYTHON="${PYTHON:-python3}"
$PYTHON -m pip -q install -U pip
$PYTHON -m pip -q install -U 'transformers>=4.51.0' accelerate pillow pandas numpy \
  sentencepiece protobuf einops torchvision || true
$PYTHON -m pip -q install -U addict easydict || true
$PYTHON -m pip -q install -U qwen-vl-utils || true
# optional 4bit fallback for 7B on 16GB
$PYTHON -m pip -q install -U bitsandbytes || true

$PYTHON - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0),
          "vram_gb", round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1))
PY

aws s3 cp "s3://${BUCKET}/${PREFIX}/sample_ids.txt" "data/qa/${PREFIX}/sample_ids.txt"
aws s3 cp "s3://${BUCKET}/${PREFIX}/posters.csv" data/posters.csv
# Mixed-source posters staged under PREFIX/posters/ (homolog / hi-res / w342)
aws s3 sync "s3://${BUCKET}/${PREFIX}/posters/" data/posters_hard/ --size-only
aws s3 cp "s3://${BUCKET}/${PREFIX}/sample_meta.csv" "data/qa/${PREFIX}/sample_meta.csv" 2>/dev/null || true
aws s3 cp "s3://${BUCKET}/${PREFIX}/poster_sources.csv" "data/qa/${PREFIX}/poster_sources.csv" 2>/dev/null || true

N_JPG=$(ls data/posters_hard/*.jpg 2>/dev/null | wc -l | tr -d ' ')
MAX_N="${MAX_N:-120}"
echo "local hard posters: $N_JPG"
if [ "$N_JPG" -eq 0 ]; then
  echo "ERROR: no posters downloaded"; exit 1
fi
if [ "$N_JPG" -gt "$MAX_N" ]; then
  echo "ERROR: refusing to run — too many posters ($N_JPG > $MAX_N)"
  exit 1
fi

sync_results() {
  if [ -d "data/qa/${PREFIX}" ]; then
    aws s3 sync "data/qa/${PREFIX}/" "s3://${BUCKET}/${PREFIX}/results/" \
      --exclude "*" --include "*.csv" --include "*.txt" --include "*.log" --include "DONE" || true
  fi
}

periodic_sync_loop() {
  while true; do
    sleep "$SYNC_SECS"
    if [ -f "data/qa/${PREFIX}/.stop_sync" ]; then
      break
    fi
    echo "[periodic-sync $(date -u +%H:%M:%S)] → s3://${BUCKET}/${PREFIX}/results/"
    sync_results
  done
}

echo "--- verify S3 write ---"
echo "S3_WRITE_OK_$(date -u +%Y%m%dT%H%M%SZ)" > "data/qa/${PREFIX}/OCR_PILOT_S3_PROBE"
aws s3 cp "data/qa/${PREFIX}/OCR_PILOT_S3_PROBE" "s3://${BUCKET}/${PREFIX}/results/OCR_PILOT_S3_PROBE"
echo "S3 write OK (SYNC_SECS=$SYNC_SECS)"

if [ -z "${MODELS:-}" ]; then
  aws s3 cp "s3://${BUCKET}/${PREFIX}/MODELS" /tmp/${PREFIX}_MODELS 2>/dev/null || true
  if [ -f /tmp/${PREFIX}_MODELS ]; then
    MODELS=$(tr -d '[:space:]' </tmp/${PREFIX}_MODELS)
    echo "MODELS from S3: $MODELS"
  fi
fi
MODELS="${MODELS:-qwen,qwen7}"
N=$(wc -l < "data/qa/${PREFIX}/sample_ids.txt" | tr -d ' ')
echo "MODELS=$MODELS N=$N"

# Map model key → result tag
result_tag_for() {
  case "$1" in
    qwen) echo "qwen2b-hard" ;;
    qwen7) echo "qwen7b-hard" ;;
    *) echo "${1}-hard" ;;
  esac
}

# Free HF cache between models so 7B download fits on small root volumes
clear_hf_cache() {
  echo "--- clearing HF cache under $HF_HOME (keep transformers metadata) ---"
  if [ -d "$HF_HOME/hub" ]; then
    du -sh "$HF_HOME/hub" 2>/dev/null || true
    # remove model blobs but keep hub structure
    find "$HF_HOME/hub" -type f \( -name '*.safetensors' -o -name '*.bin' -o -name '*.gguf' -o -name '*.msgpack' -o -name '*.h5' -o -name '*.ot' -o -name '*.pth' \) -delete 2>/dev/null || true
    find "$HF_HOME/hub" -type d -name 'blobs' -exec rm -rf {} + 2>/dev/null || true
    # incomplete downloads
    find "$HF_HOME" -name '*.incomplete' -delete 2>/dev/null || true
    df -h / /home/ubuntu 2>/dev/null || df -h /
  fi
}

aws s3 cp "s3://${BUCKET}/${PREFIX}/results/results.csv" \
  "data/qa/${PREFIX}/results.csv" 2>/dev/null || true
aws s3 rm "s3://${BUCKET}/${PREFIX}/results/DONE" 2>/dev/null || true
rm -f "data/qa/${PREFIX}/DONE" "data/qa/${PREFIX}/.stop_sync"

rm -f "data/qa/${PREFIX}/.stop_sync"
periodic_sync_loop &
SYNC_PID=$!
echo "periodic sync pid=$SYNC_PID every ${SYNC_SECS}s"

cleanup_sync() {
  touch "data/qa/${PREFIX}/.stop_sync"
  wait "$SYNC_PID" 2>/dev/null || true
}
trap cleanup_sync EXIT

IFS=',' read -ra MODEL_ARR <<< "$MODELS"
idx=0
for m in "${MODEL_ARR[@]}"; do
  m=$(echo "$m" | tr -d ' ')
  [ -z "$m" ] && continue
  RESULT_MODEL=$(result_tag_for "$m")
  if [ "$idx" -gt 0 ]; then
    clear_hf_cache
  fi
  echo "--- disk before $m ---"
  df -h / /home/ubuntu 2>/dev/null || df -h /
  echo "--- run model=$m result=$RESULT_MODEL $(date -u) ---"
  set +e
  $PYTHON -u pilot_ocr_models.py \
    --n "$N" \
    --ids-file "data/qa/${PREFIX}/sample_ids.txt" \
    --out-dir "data/qa/${PREFIX}" \
    --posters-dir data/posters_hard \
    --models "$m" \
    --result-model "$RESULT_MODEL" \
    --append-results
  rc=$?
  set -e
  echo "model=$m result=$RESULT_MODEL exit=$rc"
  sync_results
  echo "[checkpoint] synced after $m / $RESULT_MODEL"
  idx=$((idx + 1))
done

date -u +"${PREFIX}_DONE_%Y%m%dT%H%M%SZ" > "data/qa/${PREFIX}/DONE"
aws s3 cp "data/qa/${PREFIX}/DONE" "s3://${BUCKET}/${PREFIX}/results/DONE"
sync_results
echo "=== ${PREFIX}_chain done $(date -u) ==="
sleep 15
sudo shutdown -h now
