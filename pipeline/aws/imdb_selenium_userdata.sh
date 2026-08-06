#!/bin/bash
# cloud-init: IMDb Selenium on workshop EC2 (Xvfb + Chrome headed).
# Defaults match AWS_PROFILE=sandbox workshop account.
exec > >(tee /home/ubuntu/imdb_selenium_userdata.log) 2>&1
set -euo pipefail
export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-imdb-selenium}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export MODE="${MODE:-features}"
export LIMIT="${LIMIT:-0}"
export DELAY="${DELAY:-1.4}"
export PATH=/usr/local/bin:$PATH

echo "=== imdb_selenium userdata start $(date -u) ==="
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
mkdir -p "$PIPE/data/qa" "$PIPE/aws"

# Ubuntu 24.04 AMI often lacks AWS CLI — install v2 before any aws s3/sts calls
ensure_aws_cli() {
  if command -v aws >/dev/null 2>&1; then
    echo "aws cli present: $(command -v aws) ($(aws --version 2>&1 | head -1))"
    return 0
  fi
  echo "--- install AWS CLI v2 ---"
  apt-get update -y
  apt-get install -y curl unzip ca-certificates
  tmp="$(mktemp -d)"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "$tmp/awscliv2.zip"
  unzip -q "$tmp/awscliv2.zip" -d "$tmp"
  "$tmp/aws/install" -i /usr/local/aws-cli -b /usr/local/bin
  rm -rf "$tmp"
  hash -r || true
  export PATH=/usr/local/bin:$PATH
  command -v aws >/dev/null 2>&1 || {
    echo "ERROR: AWS CLI install failed"
    exit 1
  }
  echo "aws cli installed: $(aws --version 2>&1 | head -1)"
}
ensure_aws_cli

for i in $(seq 1 40); do
  if aws sts get-caller-identity >/dev/null 2>&1; then break; fi
  sleep 3
done
aws sts get-caller-identity || true

# Optional runtime overrides staged to S3
if aws s3 cp "s3://${BUCKET}/${PREFIX}/ENV" /tmp/imdb_selenium_env 2>/dev/null; then
  set -a
  # shellcheck disable=SC1091
  source /tmp/imdb_selenium_env
  set +a
fi

echo "--- pull code + chain ---"
aws s3 sync "s3://${BUCKET}/${PREFIX}/code/" "$PIPE/"
chmod +x "$PIPE/aws/imdb_selenium_chain.sh" || true

# secret key file if staged
mkdir -p "$PIPE/data/qa"
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/qa/tmdb_api_key" "$PIPE/data/qa/tmdb_api_key" 2>/dev/null || true

chown -R ubuntu:ubuntu "$ROOT"
sudo -u ubuntu -H env \
  BUCKET="$BUCKET" PREFIX="$PREFIX" MODE="$MODE" LIMIT="$LIMIT" DELAY="$DELAY" \
  TMDB_API_KEY="${TMDB_API_KEY:-}" AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
  PATH="/usr/local/bin:$PATH" \
  bash -lc "cd $PIPE && bash aws/imdb_selenium_chain.sh"

echo "=== userdata done — shutdown $(date -u) ==="
shutdown -h now
