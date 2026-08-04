#!/bin/bash
# Community-72k Labels-ONLY re-run (retry AccessDenied after IAM fix).
# Does NOT download posters / DetectText. Halts when done.
set -euo pipefail
export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-community-72k}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION required}"
export REK_WORKERS="${REK_WORKERS:-10}"
export MIN_INTERVAL="${MIN_INTERVAL:-0.04}"
export SAVE_EVERY="${SAVE_EVERY:-25}"
export SYNC_SECS="${SYNC_SECS:-60}"
export WORK_DIR="${WORK_DIR:-/home/ubuntu/aof/pipeline}"

ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
QA=$PIPE/data/qa/community_72k
LOG=$QA/community_72k_relabels.log
mkdir -p "$QA" "$PIPE/aws" "$PIPE/data"
exec > >(tee -a "$LOG") 2>&1

echo "=== community_72k RELABELS chain start $(date -u) ==="
cd "$PIPE"

if aws s3 cp "s3://${BUCKET}/${PREFIX}/ENV" /tmp/community_72k_env 2>/dev/null; then
  set -a
  # shellcheck disable=SC1091
  source /tmp/community_72k_env
  set +a
fi

aws s3 sync "s3://${BUCKET}/${PREFIX}/code/" "$PIPE/" || true
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/qa/skip_labels_ids.txt" "$QA/skip_labels_ids.txt" 2>/dev/null || true
# Resume checkpoint (AccessDenied rows already stripped on S3)
aws s3 cp "s3://${BUCKET}/${PREFIX}/results/rekognition_community_72k.csv" \
  "$QA/rekognition_community_72k.csv" 2>/dev/null || true
aws s3 cp "s3://${BUCKET}/${PREFIX}/results/tmdb_horror_ids.csv" \
  "$QA/tmdb_horror_ids.csv" 2>/dev/null || \
  aws s3 cp "s3://${BUCKET}/${PREFIX}/input/tmdb_horror_ids.csv" \
  "$QA/tmdb_horror_ids.csv"

VENV=/home/ubuntu/aof/.venv
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip -q install -U pip
python -m pip -q install -U boto3 requests botocore
PYTHON="$VENV/bin/python"
export PATH="$VENV/bin:$PATH"

echo "--- S3 write probe ---"
echo "S3_WRITE_OK_RELABELS_$(date -u +%Y%m%dT%H%M%SZ)" > "$QA/S3_PROBE"
aws s3 cp "$QA/S3_PROBE" "s3://${BUCKET}/${PREFIX}/results/S3_PROBE"
echo "S3 write OK"

sync_log() {
  [ -f "$LOG" ] && aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/community_72k_relabels.log" --quiet || true
  [ -f "$QA/PROGRESS.json" ] && aws s3 cp "$QA/PROGRESS.json" "s3://${BUCKET}/${PREFIX}/results/PROGRESS.json" --quiet || true
  [ -f "$QA/rekognition_community_72k.csv" ] && \
    aws s3 cp "$QA/rekognition_community_72k.csv" \
      "s3://${BUCKET}/${PREFIX}/results/rekognition_community_72k.csv" --quiet || true
}

periodic_sync_loop() {
  while true; do
    sleep "$SYNC_SECS"
    if [ -f "$QA/.stop_sync" ]; then
      break
    fi
    echo "[periodic-sync $(date -u +%H:%M:%S)]"
    sync_log
  done
}

periodic_sync_loop &
SYNC_PID=$!

echo "--- run community_72k_aws_worker --phase labels ---"
set +e
"$PYTHON" -u community_72k_aws_worker.py \
  --phase labels \
  --rek-workers "$REK_WORKERS" \
  --min-interval "$MIN_INTERVAL" \
  --save-every "$SAVE_EVERY" \
  --skip-labels-file "$QA/skip_labels_ids.txt"
RC=$?
set -e

touch "$QA/.stop_sync"
wait "$SYNC_PID" 2>/dev/null || true
sync_log

if [ "$RC" -eq 0 ]; then
  date -u +"DONE_RELABELS_%Y%m%dT%H%M%SZ" > "$QA/DONE"
  echo "rc=0" >> "$QA/DONE"
  aws s3 cp "$QA/DONE" "s3://${BUCKET}/${PREFIX}/results/DONE"
  aws s3 cp "$QA/DONE" "s3://${BUCKET}/${PREFIX}/results/DONE_RELABELS"
  echo "=== community_72k RELABELS DONE $(date -u) ==="
else
  echo "FAIL_RELABELS_$RC" > "$QA/FAIL"
  date -u >> "$QA/FAIL"
  aws s3 cp "$QA/FAIL" "s3://${BUCKET}/${PREFIX}/results/FAIL" || true
  aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/community_72k_relabels.log" || true
  echo "=== community_72k RELABELS FAILED rc=$RC $(date -u) ==="
fi

echo "=== chain exit — shutdown $(date -u) ==="
shutdown -h now || true
