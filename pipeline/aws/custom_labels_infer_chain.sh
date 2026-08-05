#!/bin/bash
# EC2 chain: wait Custom Labels RUNNING → DetectCustomLabels over S3 posters → sync CSV.
#
# Env: BUCKET, PREFIX, VERSION_ARN, PROJECT_ARN, POSTER_BUCKET, POSTER_PREFIX,
#      WORKERS, MIN_INTERVAL, LIMIT, STOP_MODEL_ON_DONE
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export NO_PROXY="${NO_PROXY:-*}"
export no_proxy="${no_proxy:-*}"
export BUCKET="${BUCKET:?BUCKET required}"
export PREFIX="${PREFIX:-wflike-custom-labels/infer}"
export VERSION_ARN="${VERSION_ARN:?VERSION_ARN required}"
export PROJECT_ARN="${PROJECT_ARN:?PROJECT_ARN required}"
export POSTER_BUCKET="${POSTER_BUCKET:-$BUCKET}"
export POSTER_PREFIX="${POSTER_PREFIX:-wflike-community-72k/posters}"
export WORKERS="${WORKERS:-8}"
export MIN_INTERVAL="${MIN_INTERVAL:-0.05}"
export LIMIT="${LIMIT:-0}"
export SYNC_SECS="${SYNC_SECS:-120}"
export STOP_MODEL_ON_DONE="${STOP_MODEL_ON_DONE:-1}"
export MIN_IU="${MIN_IU:-1}"
export PATH="/usr/local/bin:/usr/bin:$PATH"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
QA="$PIPE/data/qa/medium_custom_labels"
LOG="$QA/infer_ec2.log"
mkdir -p "$QA" "$PIPE/aws"
exec > >(tee -a "$LOG") 2>&1

apt_retry() {
  local n=0 max=8
  while [ "$n" -lt "$max" ]; do
    n=$((n + 1))
    echo "apt_retry[$n/$max]: $*"
    if "$@"; then return 0; fi
    echo "apt failed attempt $n — backoff + regional mirror"
    if [ -f /etc/apt/sources.list ]; then
      sudo sed -i.bak \
        -e 's|http://[a-zA-Z0-9.-]*archive.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
        -e 's|https://[a-zA-Z0-9.-]*archive.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
        -e 's|http://security.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
        -e 's|https://security.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
        /etc/apt/sources.list || true
    fi
    sleep $((n * 15))
  done
  return 1
}

echo "=== custom_labels_infer_chain start $(date -u) ==="
echo "bucket=s3://${BUCKET}/${PREFIX}/ posters=s3://${POSTER_BUCKET}/${POSTER_PREFIX}/"
echo "workers=$WORKERS interval=$MIN_INTERVAL limit=$LIMIT min_iu=$MIN_IU"
aws sts get-caller-identity || true

if aws s3 cp "s3://${BUCKET}/${PREFIX}/ENV" /tmp/cl_infer_env 2>/dev/null; then
  set -a
  # shellcheck disable=SC1091
  source /tmp/cl_infer_env
  set +a
fi

aws s3 sync "s3://${BUCKET}/${PREFIX}/code/" "$PIPE/" --exclude 'data/*' || true
chmod +x "$PIPE/aws/custom_labels_infer_chain.sh" || true

if ! python3 -c 'import venv' 2>/dev/null; then
  apt_retry sudo apt-get update -y || true
  apt_retry sudo apt-get install -y python3-venv python3-pip python3-full || true
fi
VENV=/home/ubuntu/aof/.venv-cl
rm -rf "$VENV" 2>/dev/null || true
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip -q install -U pip
python -m pip -q install -U boto3 botocore
PYTHON="$VENV/bin/python"
export PATH="$VENV/bin:$PATH"

# pull ids + resume CSV
aws s3 cp "s3://${BUCKET}/${PREFIX}/infer_ids.txt" "$QA/infer_ids.txt"
aws s3 cp "s3://${BUCKET}/${PREFIX}/results/infer_full.csv" "$QA/infer_full.csv" 2>/dev/null || true

echo "--- S3 write probe ---"
echo "S3_WRITE_OK_$(date -u +%Y%m%dT%H%M%SZ)" > "$QA/S3_PROBE"
aws s3 cp "$QA/S3_PROBE" "s3://${BUCKET}/${PREFIX}/results/S3_PROBE"

# Start model ONLY when EC2 is ready to DetectCustomLabels (avoid idle IU billing).
VERSION_NAME="${VERSION_NAME:-$(echo "$VERSION_ARN" | sed -n 's|.*/version/\([^/]*\)/.*|\1|p')}"
echo "--- StartProjectVersion (MinInferenceUnits=$MIN_IU) right before infer ---"
for _ in $(seq 1 40); do
  ST=$(aws rekognition describe-project-versions \
    --project-arn "$PROJECT_ARN" \
    --version-names "$VERSION_NAME" \
    --query 'ProjectVersionDescriptions[0].Status' --output text 2>/dev/null || echo UNKNOWN)
  echo "model_prestart_status=$ST"
  case "$ST" in
    RUNNING|STARTING) break ;;
    STOPPING)
      echo "waiting for STOPPED before start…"
      sleep 15
      ;;
    *)
      aws rekognition start-project-version \
        --project-version-arn "$VERSION_ARN" \
        --min-inference-units "$MIN_IU" || true
      break
      ;;
  esac
done

# background sync of CSV + progress + log
(
  while true; do
    sleep "$SYNC_SECS"
    aws s3 cp "$QA/infer_full.csv" "s3://${BUCKET}/${PREFIX}/results/infer_full.csv" --only-show-errors 2>/dev/null || true
    aws s3 cp "$QA/infer_full.progress.json" "s3://${BUCKET}/${PREFIX}/results/progress.json" --only-show-errors 2>/dev/null || true
    aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/infer_ec2.log" --only-show-errors 2>/dev/null || true
  done
) &
SYNC_PID=$!

echo "--- infer ---"
set +e
"$PYTHON" -u "$PIPE/aws_custom_labels_infer.py" \
  --region "$AWS_DEFAULT_REGION" \
  --version-arn "$VERSION_ARN" \
  --bucket "$POSTER_BUCKET" \
  --poster-prefix "$POSTER_PREFIX" \
  --ids-file "$QA/infer_ids.txt" \
  --out "$QA/infer_full.csv" \
  --progress "$QA/infer_full.progress.json" \
  --workers "$WORKERS" \
  --min-interval "$MIN_INTERVAL" \
  --limit "$LIMIT" \
  --wait-running \
  --wait-seconds 30 \
  --wait-timeout 3600
RC=$?
set -e
echo "infer_exit=$RC"

kill "$SYNC_PID" 2>/dev/null || true
aws s3 cp "$QA/infer_full.csv" "s3://${BUCKET}/${PREFIX}/results/infer_full.csv" --only-show-errors || true
aws s3 cp "$QA/infer_full.progress.json" "s3://${BUCKET}/${PREFIX}/results/progress.json" --only-show-errors || true
aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/infer_ec2.log" --only-show-errors || true

# Always try to stop model (even on failure) — never leave IU billing idle.
if [ "$STOP_MODEL_ON_DONE" = "1" ]; then
  echo "--- StopProjectVersion (save inference-unit hours) ---"
  aws rekognition stop-project-version --project-version-arn "$VERSION_ARN" || true
fi

if [ "$RC" -eq 0 ]; then
  date -u +"DONE_%Y%m%dT%H%M%SZ" > "$QA/INFER_DONE"
  aws s3 cp "$QA/INFER_DONE" "s3://${BUCKET}/${PREFIX}/results/DONE"
fi

echo "=== custom_labels_infer_chain end $(date -u) rc=$RC ==="
exit "$RC"
