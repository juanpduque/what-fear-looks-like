#!/bin/bash
# OWLv2 creature backfill + weapons on EC2 GPU.
# Periodic S3 checkpoint, DONE marker, then halt.
set -euo pipefail
export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-owlv2-backfill}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH
export HF_HOME="${HF_HOME:-/home/ubuntu/.cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
export SYNC_SECS="${SYNC_SECS:-180}"
export CHECKPOINT_EVERY="${CHECKPOINT_EVERY:-25}"

ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
QA=$PIPE/data/qa/owlv2_backfill
LOG=$QA/owlv2_backfill_aws.log
mkdir -p "$PIPE/data/posters" "$QA" "$PIPE/aws" "$PIPE/data"
exec > >(tee -a "$LOG") 2>&1

echo "=== owlv2_backfill_chain start $(date -u) ==="
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
$PYTHON -m pip -q install -U 'transformers>=4.45' accelerate pillow pandas numpy

$PYTHON - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0),
          "vram_gb", round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1))
else:
    raise SystemExit("CUDA not available")
PY

echo "--- pull inputs ---"
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/owlv2_creature_boxes.py" owlv2_creature_boxes.py
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/backfill_ids.txt" "$QA/backfill_ids.txt"
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/backfill_meta.json" "$QA/backfill_meta.json" || true
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/creature_boxes_existing.json" \
  data/creature_boxes_existing.json

# Resume prior delta / weapon checkpoints if any
aws s3 cp "s3://${BUCKET}/${PREFIX}/results/creature_boxes_delta.json" \
  data/creature_boxes_delta.json 2>/dev/null || echo '{}' > data/creature_boxes_delta.json
aws s3 cp "s3://${BUCKET}/${PREFIX}/results/weapon_boxes.json" \
  data/weapon_boxes.json 2>/dev/null || echo '{}' > data/weapon_boxes.json

echo "--- sync posters ---"
aws s3 sync "s3://${BUCKET}/${PREFIX}/posters/" data/posters/ --size-only
N_JPG=$(ls data/posters/*.jpg 2>/dev/null | wc -l | tr -d ' ')
N_IDS=$(grep -cve '^\s*$' "$QA/backfill_ids.txt" || true)
echo "local_posters=$N_JPG ids=$N_IDS"
if [ "$N_JPG" -lt 100 ]; then
  echo "ERROR: too few posters ($N_JPG)"; exit 1
fi

sync_results() {
  aws s3 cp data/creature_boxes_delta.json \
    "s3://${BUCKET}/${PREFIX}/results/creature_boxes_delta.json" --quiet || true
  aws s3 cp data/weapon_boxes.json \
    "s3://${BUCKET}/${PREFIX}/results/weapon_boxes.json" --quiet || true
  [ -f "$LOG" ] && aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/owlv2_backfill_aws.log" --quiet || true
  # progress count
  $PYTHON - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
c=json.loads(Path("data/creature_boxes_delta.json").read_text()) if Path("data/creature_boxes_delta.json").exists() else {}
w=json.loads(Path("data/weapon_boxes.json").read_text()) if Path("data/weapon_boxes.json").exists() else {}
Path("data/qa/owlv2_backfill/PROGRESS").write_text(
    f"creature_delta={len(c)}\nweapon={len(w)}\n", encoding="utf-8")
print(f"progress creature_delta={len(c)} weapon={len(w)}")
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
echo "S3 write OK (SYNC_SECS=$SYNC_SECS CHECKPOINT_EVERY=$CHECKPOINT_EVERY)"

periodic_sync_loop &
SYNC_PID=$!

echo "--- run OWLv2 creature+weapon backfill ---"
set +e
$PYTHON -u owlv2_creature_boxes.py \
  --ids-file "$QA/backfill_ids.txt" \
  --with-weapons \
  --device cuda \
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
  echo "=== owlv2_backfill DONE $(date -u) ==="
else
  echo "FAIL_$RC" > "$QA/FAIL"
  date -u >> "$QA/FAIL"
  aws s3 cp "$QA/FAIL" "s3://${BUCKET}/${PREFIX}/results/FAIL" || true
  echo "=== owlv2_backfill FAILED rc=$RC $(date -u) ==="
fi

sync_results
echo "=== chain exit — shutdown $(date -u) ==="
shutdown -h now || true
