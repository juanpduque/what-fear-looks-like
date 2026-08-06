#!/bin/bash
# cloud-init: community-72k enumerate → S3 posters → Rekognition.
exec > >(tee /home/ubuntu/community_72k_userdata.log) 2>&1
set -euo pipefail
export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-community-72k}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export PATH=/usr/local/bin:$PATH

echo "=== community_72k userdata start $(date -u) ==="
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
mkdir -p "$PIPE/data/qa" "$PIPE/aws"

ensure_aws_cli() {
  if command -v aws >/dev/null 2>&1; then
    echo "aws cli present: $(command -v aws)"
    return 0
  fi
  echo "--- install AWS CLI v2 ---"
  apt-get update -y
  apt-get install -y curl unzip ca-certificates python3 python3-pip python3-venv
  tmp="$(mktemp -d)"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "$tmp/awscliv2.zip"
  unzip -q "$tmp/awscliv2.zip" -d "$tmp"
  "$tmp/aws/install" -i /usr/local/aws-cli -b /usr/local/bin
  rm -rf "$tmp"
  hash -r || true
  export PATH=/usr/local/bin:$PATH
}
ensure_aws_cli

# base packages (python3-venv required for PEP 668 workaround)
apt-get update -y || true
apt-get install -y python3 python3-pip python3-venv python3-full curl unzip ca-certificates || true

for i in $(seq 1 40); do
  if aws sts get-caller-identity >/dev/null 2>&1; then break; fi
  sleep 3
done
aws sts get-caller-identity || true

if aws s3 cp "s3://${BUCKET}/${PREFIX}/ENV" /tmp/community_72k_env 2>/dev/null; then
  set -a
  # shellcheck disable=SC1091
  source /tmp/community_72k_env
  set +a
fi

echo "--- pull code ---"
aws s3 sync "s3://${BUCKET}/${PREFIX}/code/" "$PIPE/"
chmod +x "$PIPE/aws/community_72k_chain.sh" || true

mkdir -p "$PIPE/data/qa/community_72k"
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/qa/tmdb_api_key" \
  "$PIPE/data/qa/community_72k/tmdb_api_key" 2>/dev/null || true
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/qa/skip_labels_ids.txt" \
  "$PIPE/data/qa/community_72k/skip_labels_ids.txt" 2>/dev/null || true
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/qa/skip_detecttext_ids.txt" \
  "$PIPE/data/qa/community_72k/skip_detecttext_ids.txt" 2>/dev/null || true
chmod 600 "$PIPE/data/qa/community_72k/tmdb_api_key" 2>/dev/null || true

export TMDB_API_KEY
TMDB_API_KEY="$(cat "$PIPE/data/qa/community_72k/tmdb_api_key" 2>/dev/null || true)"

chown -R ubuntu:ubuntu "$ROOT"
sudo -u ubuntu -H env \
  BUCKET="$BUCKET" PREFIX="$PREFIX" \
  TMDB_API_KEY="$TMDB_API_KEY" \
  AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
  DOWNLOAD_WORKERS="${DOWNLOAD_WORKERS:-24}" \
  REK_WORKERS="${REK_WORKERS:-10}" \
  MIN_INTERVAL="${MIN_INTERVAL:-0.04}" \
  SAVE_EVERY="${SAVE_EVERY:-25}" \
  SYNC_SECS="${SYNC_SECS:-120}" \
  PATH="/usr/local/bin:$PATH" \
  bash -lc "cd $PIPE && bash aws/community_72k_chain.sh"

echo "=== userdata done — shutdown $(date -u) ==="
shutdown -h now
