#!/bin/bash
# OWLv2 backfill CPU-only (resume from S3 deltas). Never GPU.
# After OOM on c5.2xlarge: prefer c5.4xlarge (32GB). Halts when done.
set -euo pipefail
export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-owlv2-backfill}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION required}"
export SYNC_SECS="${SYNC_SECS:-180}"
export CHECKPOINT_EVERY="${CHECKPOINT_EVERY:-25}"
export DEVICE=cpu
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export TOKENIZERS_PARALLELISM=false

ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
QA=$PIPE/data/qa/owlv2_backfill
LOG=$QA/owlv2_backfill_aws.log
mkdir -p "$PIPE/data/posters" "$QA" "$PIPE/aws" "$PIPE/data"
exec > >(tee -a "$LOG") 2>&1

echo "=== owlv2_backfill_chain start (CPU) $(date -u) ==="
cd "$PIPE"

if aws s3 cp "s3://${BUCKET}/${PREFIX}/ENV" /tmp/owlv2_backfill_env 2>/dev/null; then
  set -a
  # shellcheck disable=SC1091
  source /tmp/owlv2_backfill_env
  set +a
fi
# Force CPU even if ENV says cuda
export DEVICE=cpu

aws s3 cp "s3://${BUCKET}/${PREFIX}/code/owlv2_creature_boxes.py" owlv2_creature_boxes.py
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/aws/owlv2_backfill_chain_cpu.sh" "$PIPE/aws/owlv2_backfill_chain_cpu.sh" 2>/dev/null || true

VENV=/home/ubuntu/owlvenv
if [ ! -x "$VENV/bin/python" ]; then
  echo "--- create venv $VENV ---"
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
PYTHON="$VENV/bin/python"
export PATH="$VENV/bin:/usr/local/bin:$PATH"

echo "--- install torch CPU wheels ---"
python -m pip -q install -U pip
python -m pip -q install -U 'torch' --index-url https://download.pytorch.org/whl/cpu
python -m pip -q install -U 'transformers>=4.45' accelerate pillow pandas numpy
$PYTHON - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
print("threads", torch.get_num_threads())
print("device_count", torch.cuda.device_count())
assert not torch.cuda.is_available(), "CUDA must stay off for this job"
PY

echo "--- pull inputs + resume checkpoints ---"
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/backfill_ids.txt" "$QA/backfill_ids.txt"
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/backfill_meta.json" "$QA/backfill_meta.json" || true
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/creature_boxes_existing.json" \
  data/creature_boxes_existing.json
aws s3 cp "s3://${BUCKET}/${PREFIX}/results/creature_boxes_delta.json" \
  data/creature_boxes_delta.json 2>/dev/null || echo '{}' > data/creature_boxes_delta.json
aws s3 cp "s3://${BUCKET}/${PREFIX}/results/weapon_boxes.json" \
  data/weapon_boxes.json 2>/dev/null || echo '{}' > data/weapon_boxes.json

echo "--- sync posters ---"
aws s3 sync "s3://${BUCKET}/${PREFIX}/posters/" data/posters/ --size-only
N_JPG=$(find data/posters -name '*.jpg' | wc -l | tr -d ' ')
N_IDS=$(grep -cve '^\s*$' "$QA/backfill_ids.txt" || true)
echo "local_posters=$N_JPG ids=$N_IDS device=$DEVICE"
if [ "$N_JPG" -lt 100 ]; then
  echo "ERROR: too few posters ($N_JPG)"; exit 1
fi

sync_results() {
  aws s3 cp data/creature_boxes_delta.json \
    "s3://${BUCKET}/${PREFIX}/results/creature_boxes_delta.json" --quiet || true
  aws s3 cp data/weapon_boxes.json \
    "s3://${BUCKET}/${PREFIX}/results/weapon_boxes.json" --quiet || true
  [ -f "$LOG" ] && aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/owlv2_backfill_aws.log" --quiet || true
  $PYTHON - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
from datetime import datetime, timezone
c=json.loads(Path("data/creature_boxes_delta.json").read_text()) if Path("data/creature_boxes_delta.json").exists() else {}
w=json.loads(Path("data/weapon_boxes.json").read_text()) if Path("data/weapon_boxes.json").exists() else {}
ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
Path("data/qa/owlv2_backfill/PROGRESS").write_text(
    f"creature_delta={len(c)}\nweapon={len(w)}\nts={ts}\ndevice=cpu\n", encoding="utf-8")
print(f"progress creature_delta={len(c)} weapon={len(w)} ts={ts}")
PY
  aws s3 cp "$QA/PROGRESS" "s3://${BUCKET}/${PREFIX}/results/PROGRESS" --quiet || true
}

periodic_sync_loop() {
  while true; do
    sleep "$SYNC_SECS"
    if [ -f "$QA/.stop_sync" ]; then
      break
    fi
    echo "[periodic-sync $(date -u +%H:%M:%S)] → s3://${BUCKET}/${PREFIX}/results/"
    sync_results
  done
}

echo "--- verify S3 write ---"
echo "S3_WRITE_OK_$(date -u +%Y%m%dT%H%M%SZ)" > "$QA/S3_PROBE"
aws s3 cp "$QA/S3_PROBE" "s3://${BUCKET}/${PREFIX}/results/S3_PROBE"
# clear prior FAIL so dashboard can flip to running
aws s3 rm "s3://${BUCKET}/${PREFIX}/results/FAIL" 2>/dev/null || true
echo "S3 write OK (SYNC_SECS=$SYNC_SECS CHECKPOINT_EVERY=$CHECKPOINT_EVERY DEVICE=$DEVICE)"
sync_results

periodic_sync_loop &
SYNC_PID=$!

echo "--- run OWLv2 creature+weapon backfill (CPU resume) ---"
set +e
$PYTHON -u owlv2_creature_boxes.py \
  --ids-file "$QA/backfill_ids.txt" \
  --with-weapons \
  --device cpu \
  --min-score 0.2 \
  --creature-out data/creature_boxes_delta.json \
  --weapon-out data/weapon_boxes.json \
  --protect-creature-from data/creature_boxes_existing.json \
  --no-site-js \
  --checkpoint-every "$CHECKPOINT_EVERY" \
  --posters-dir data/posters
RC=$?
set -e

touch "$QA/.stop_sync"
wait "$SYNC_PID" 2>/dev/null || true
sync_results

if [ "$RC" -eq 0 ]; then
  date -u +"DONE_%Y%m%dT%H%M%SZ" > "$QA/DONE"
  echo "rc=0" >> "$QA/DONE"
  aws s3 cp "$QA/DONE" "s3://${BUCKET}/${PREFIX}/results/DONE"
  aws s3 rm "s3://${BUCKET}/${PREFIX}/results/FAIL" 2>/dev/null || true
  echo "=== owlv2_backfill DONE $(date -u) ==="
else
  echo "FAIL_$RC" > "$QA/FAIL"
  date -u >> "$QA/FAIL"
  echo "device=cpu" >> "$QA/FAIL"
  aws s3 cp "$QA/FAIL" "s3://${BUCKET}/${PREFIX}/results/FAIL" || true
  aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/owlv2_backfill_aws.log" || true
  echo "=== owlv2_backfill FAILED rc=$RC $(date -u) ==="
fi

echo "=== chain exit — shutdown $(date -u) ==="
sudo shutdown -h now || shutdown -h now || true
