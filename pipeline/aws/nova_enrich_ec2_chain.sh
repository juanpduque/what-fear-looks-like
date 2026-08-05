#!/bin/bash
# EC2 chain: pull staged Nova enrich posters from S3 → Bedrock Converse direct → sync results.
#
# Env: BUCKET, PREFIX, BEDROCK_REGION, WORKERS, MIN_INTERVAL, LIMIT
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export BEDROCK_REGION="${BEDROCK_REGION:-us-east-1}"
export NO_PROXY="${NO_PROXY:-*}"
export no_proxy="${no_proxy:-*}"
export BUCKET="${BUCKET:?BUCKET required}"
export PREFIX="${PREFIX:-wflike-nova-enrich/cloud}"
export WORKERS="${WORKERS:-4}"
export MIN_INTERVAL="${MIN_INTERVAL:-0.55}"
export LIMIT="${LIMIT:-0}"
export SYNC_SECS="${SYNC_SECS:-90}"
export PATH="/usr/local/bin:/usr/bin:$PATH"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
QA="$PIPE/data/qa/nova_enrich"
LOG="$QA/nova_enrich_ec2.log"
mkdir -p "$QA/json" "$PIPE/data/posters" "$PIPE/aws"
exec > >(tee -a "$LOG") 2>&1

echo "=== nova_enrich_ec2_chain start $(date -u) ==="
echo "bucket=s3://${BUCKET}/${PREFIX}/ bedrock_region=$BEDROCK_REGION workers=$WORKERS"
if ! command -v aws >/dev/null 2>&1; then
  echo "ERROR: aws CLI not on PATH"
  exit 1
fi
aws sts get-caller-identity || true

if aws s3 cp "s3://${BUCKET}/${PREFIX}/ENV" /tmp/nova_enrich_env 2>/dev/null; then
  set -a
  # shellcheck disable=SC1091
  source /tmp/nova_enrich_env
  set +a
fi

# Refresh code
aws s3 sync "s3://${BUCKET}/${PREFIX}/code/" "$PIPE/" --exclude 'data/*' || true
chmod +x "$PIPE/aws/nova_enrich_ec2_chain.sh" || true

# Ubuntu 24.04 PEP 668 — ensure venv package exists (userdata should have installed it)
if ! python3 -c 'import venv' 2>/dev/null; then
  echo "--- install python3-venv (chain fallback, apt-retry) ---"
  for n in 1 2 3 4 5 6 7 8; do
    if sudo apt-get update -y && sudo apt-get install -y python3-venv python3-pip python3-full; then
      break
    fi
    echo "apt failed attempt $n — switch to us-east-1 ec2 mirror"
    sudo sed -i.bak \
      -e 's|http://[a-zA-Z0-9.-]*archive.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
      -e 's|http://security.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
      /etc/apt/sources.list || true
    sleep $((n * 15))
  done
fi
VENV=/home/ubuntu/aof/.venv-nova
rm -rf "$VENV" 2>/dev/null || true
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip -q install -U pip
python -m pip -q install -U boto3 botocore pandas pillow
PYTHON="$VENV/bin/python"
export PATH="$VENV/bin:$PATH"
"$PYTHON" -c 'import boto3, pandas, PIL; print("deps_ok", boto3.__version__)'

echo "--- Bedrock probe ($BEDROCK_REGION) ---"
"$PYTHON" - <<PY
import boto3, io
from PIL import Image
img = Image.new("RGB", (64, 64), color=(20, 20, 20))
buf = io.BytesIO(); img.save(buf, format="JPEG"); raw = buf.getvalue()
rt = boto3.client("bedrock-runtime", region_name="${BEDROCK_REGION}")
resp = rt.converse(
    modelId="us.amazon.nova-2-lite-v1:0",
    messages=[{"role": "user", "content": [
        {"image": {"format": "jpeg", "source": {"bytes": raw}}},
        {"text": "Reply OK"},
    ]}],
    inferenceConfig={"temperature": 0, "maxTokens": 8},
)
text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"] if "text" in b)
print("BEDROCK_PROBE_OK", repr(text[:40]), resp.get("usage"))
PY

echo "--- pull stage state ---"
aws s3 cp "s3://${BUCKET}/${PREFIX}/todo_ids.json" "$QA/todo_ids.json"
aws s3 cp "s3://${BUCKET}/${PREFIX}/posters_meta.json" "$QA/posters_meta.json"
aws s3 cp "s3://${BUCKET}/${PREFIX}/posters.csv" "$PIPE/data/posters.csv"
# resume CSV if present locally or on S3
aws s3 cp "s3://${BUCKET}/${PREFIX}/nova_enrich.csv" "$QA/nova_enrich.csv" 2>/dev/null || true
aws s3 sync "s3://${BUCKET}/${PREFIX}/json/" "$QA/json/" --size-only 2>/dev/null || true

echo "--- sync posters (pending only) ---"
aws s3 sync "s3://${BUCKET}/${PREFIX}/posters/" "$PIPE/data/posters/" --size-only
N_JPG=$(ls "$PIPE"/data/posters/*.jpg 2>/dev/null | wc -l | tr -d ' ')
echo "local_posters=$N_JPG"
if [ "$N_JPG" -lt 1 ]; then
  echo "ERROR: no posters downloaded"
  exit 1
fi

echo "--- S3 write probe ---"
echo "S3_WRITE_OK_$(date -u +%Y%m%dT%H%M%SZ)" > "$QA/S3_PROBE"
aws s3 cp "$QA/S3_PROBE" "s3://${BUCKET}/${PREFIX}/results/S3_PROBE"
echo "S3 write OK"

sync_results() {
  aws s3 cp "$QA/nova_enrich.csv" "s3://${BUCKET}/${PREFIX}/nova_enrich.csv" --quiet || true
  aws s3 cp "$QA/progress.json" "s3://${BUCKET}/${PREFIX}/progress_cloud.json" --quiet 2>/dev/null || true
  aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/nova_enrich_ec2.log" --quiet || true
  aws s3 sync "$QA/json/" "s3://${BUCKET}/${PREFIX}/json/" --size-only --quiet || true
  if [ -f "$QA/nova_enrich_errors.csv" ]; then
    aws s3 cp "$QA/nova_enrich_errors.csv" "s3://${BUCKET}/${PREFIX}/results/nova_enrich_errors.csv" --quiet || true
  fi
}

periodic_sync_loop() {
  while true; do
    sleep "$SYNC_SECS"
    if [ -f "$QA/.stop_sync" ]; then
      break
    fi
    echo "[periodic-sync $(date -u +%H:%M:%S)]"
    sync_results
  done
}

aws s3 rm "s3://${BUCKET}/${PREFIX}/results/DONE" 2>/dev/null || true
rm -f "$QA/DONE" "$QA/.stop_sync"
periodic_sync_loop &
SYNC_PID=$!

LIMIT_ARGS=()
if [ "${LIMIT}" != "0" ] && [ -n "${LIMIT}" ]; then
  LIMIT_ARGS=(--limit "$LIMIT")
fi

echo "--- run nova_poster_enrich --direct ---"
set +e
"$PYTHON" -u nova_poster_enrich.py \
  --direct \
  --region "$BEDROCK_REGION" \
  --model-id us.amazon.nova-2-lite-v1:0 \
  --ids-file "$QA/todo_ids.json" \
  --meta-json "$QA/posters_meta.json" \
  --workers "$WORKERS" \
  --min-interval "$MIN_INTERVAL" \
  --save-every 1 \
  --flush-seconds 30 \
  "${LIMIT_ARGS[@]}"
RC=$?
set -e

touch "$QA/.stop_sync"
wait "$SYNC_PID" 2>/dev/null || true
sync_results

if [ "$RC" -eq 0 ]; then
  date -u +"DONE_%Y%m%dT%H%M%SZ" > "$QA/DONE"
  echo "rc=0" >> "$QA/DONE"
  aws s3 cp "$QA/DONE" "s3://${BUCKET}/${PREFIX}/results/DONE"
  echo "=== chain DONE $(date -u) ==="
else
  date -u +"FAIL_%Y%m%dT%H%M%SZ" > "$QA/FAIL"
  echo "rc=$RC" >> "$QA/FAIL"
  aws s3 cp "$QA/FAIL" "s3://${BUCKET}/${PREFIX}/results/FAIL"
  echo "=== chain FAIL rc=$RC $(date -u) ==="
fi
exit "$RC"
