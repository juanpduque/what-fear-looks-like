#!/bin/bash
set -uo pipefail
cd "$(cd "$(dirname "$0")/../.." && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-sandbox}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN || true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy || true

LOG=data/ocr_comprehend_fullset_run.log
PROGRESS=data/qa/ocr_comprehend_fullset_progress.json
PYPID=data/qa/ocr_comprehend_fullset_python.pid
CHAINPID=data/qa/ocr_comprehend_fullset.pid
WORKERS="${WORKERS:-8}"
PYTHON="${PYTHON:-python3}"

echo $$ > "$CHAINPID"
echo "=== comprehend fullset START $(date -u +%Y-%m-%dT%H:%M:%SZ) workers=$WORKERS ===" | tee -a "$LOG"

run_step() {
  local phase="$1"; shift
  echo "{\"phase\":\"$phase\",\"status\":\"running\",\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$PROGRESS"
  echo "--- $phase ---" | tee -a "$LOG"
  # run in background so we can record python pid, then wait
  $PYTHON -u "$@" >>"$LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$PYPID"
  wait "$pid"
  local rc=$?
  echo "step $phase exit=$rc" | tee -a "$LOG"
  return $rc
}

run_step alllang_detecttext ocr_comprehend.py \
  --ocr-file data/poster_ocr_rek_text_alllang.csv --source detecttext \
  --out data/ocr_comprehend_alllang.csv --workers "$WORKERS" || exit 1

run_step essay_detecttext ocr_comprehend.py \
  --ocr-file data/poster_ocr_rek_text.csv --source detecttext \
  --out data/ocr_comprehend.csv --workers "$WORKERS" || exit 1

run_step essay_textract ocr_comprehend.py \
  --ocr-file data/poster_ocr_textract.csv --source textract \
  --out data/ocr_comprehend.csv --workers "$WORKERS" || exit 1

echo "{\"phase\":\"done\",\"status\":\"done\",\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$PROGRESS"
echo "=== comprehend fullset DONE $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LOG"
rm -f "$CHAINPID" "$PYPID"
