#!/bin/bash
# cloud-init: attributes-only gap (opencv-contrib + multi_analyze).
exec > >(tee /home/ubuntu/attrs_gap_userdata.log) 2>&1
set -euo pipefail
export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-attrs-gap}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export PATH=/usr/local/bin:${PATH:-}
export POSTER_SRC="${POSTER_SRC:-s3://sagemaker-studio-a5572760/wflike-community-72k/posters}"
export VISION_GAP_POSTERS="${VISION_GAP_POSTERS:-s3://sagemaker-studio-a5572760/wflike-vision-gap/input/posters}"
export SYNC_SECS="${SYNC_SECS:-180}"
export DL_WORKERS="${DL_WORKERS:-32}"

echo "=== attrs_gap userdata start $(date -u) ==="
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
mkdir -p "$PIPE/data/qa/attrs_gap" "$PIPE/aws" "$PIPE/data/posters"

apt_retry() {
  local n=0 max=8
  while [ "$n" -lt "$max" ]; do
    n=$((n + 1))
    echo "apt_retry[$n/$max]: $*"
    if "$@"; then return 0; fi
    echo "apt failed attempt $n — backoff + regional mirror"
    if [ -f /etc/apt/sources.list ]; then
      sed -i.bak \
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

ensure_aws_cli() {
  if command -v aws >/dev/null 2>&1; then
    echo "aws cli present: $(command -v aws)"
    return 0
  fi
  echo "--- install AWS CLI v2 (prefer no apt) ---"
  if ! command -v curl >/dev/null 2>&1; then
    apt_retry apt-get update -y || true
    apt_retry apt-get install -y curl ca-certificates || true
  fi
  mkdir -p /home/ubuntu
  tmp="/home/ubuntu/awscli-install-$$"
  rm -rf "$tmp"
  mkdir -p "$tmp"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "$tmp/awscliv2.zip"
  if command -v unzip >/dev/null 2>&1; then
    unzip -q "$tmp/awscliv2.zip" -d "$tmp"
  else
    python3 -c "import zipfile; zipfile.ZipFile('${tmp}/awscliv2.zip').extractall('${tmp}')"
  fi
  chmod -R a+rx "$tmp/aws" 2>/dev/null || true
  chmod +x "$tmp/aws/install" 2>/dev/null || true
  if ! bash "$tmp/aws/install" -i /usr/local/aws-cli -b /usr/local/bin; then
    echo "bash install failed; trying direct exec"
    "$tmp/aws/install" -i /usr/local/aws-cli -b /usr/local/bin
  fi
  rm -rf "$tmp"
  hash -r || true
  export PATH=/usr/local/bin:$PATH
  command -v aws >/dev/null 2>&1 || { echo "ERROR: AWS CLI install failed"; exit 1; }
  echo "aws cli installed: $(aws --version 2>&1 | head -1)"
}
ensure_aws_cli

apt_retry apt-get update -y || true
apt_retry apt-get install -y python3 python3-pip python3-venv python3-full curl unzip ca-certificates || true

for i in $(seq 1 40); do
  if aws sts get-caller-identity >/dev/null 2>&1; then break; fi
  sleep 3
done
aws sts get-caller-identity || true

if aws s3 cp "s3://${BUCKET}/${PREFIX}/ENV" /tmp/attrs_gap_env 2>/dev/null; then
  set -a
  # shellcheck disable=SC1091
  source /tmp/attrs_gap_env
  set +a
fi

echo "--- pull code + input ---"
aws s3 sync "s3://${BUCKET}/${PREFIX}/code/" "$PIPE/"
aws s3 sync "s3://${BUCKET}/${PREFIX}/input/data/" "$PIPE/data/" --exclude "posters/*"
chmod +x "$PIPE/aws/attrs_gap_chain.sh" || true

chown -R ubuntu:ubuntu "$ROOT"
sudo -u ubuntu -H env \
  BUCKET="$BUCKET" PREFIX="$PREFIX" \
  AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
  POSTER_SRC="$POSTER_SRC" \
  VISION_GAP_POSTERS="${VISION_GAP_POSTERS}" \
  SYNC_SECS="${SYNC_SECS:-180}" \
  DL_WORKERS="${DL_WORKERS:-32}" \
  OMP_NUM_THREADS="${OMP_NUM_THREADS:-16}" \
  MKL_NUM_THREADS="${MKL_NUM_THREADS:-16}" \
  PATH="/usr/local/bin:$PATH" \
  bash -lc "cd $PIPE && bash aws/attrs_gap_chain.sh"

echo "=== userdata done — shutdown $(date -u) ==="
shutdown -h now
