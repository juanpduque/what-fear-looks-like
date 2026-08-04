#!/bin/bash
# cloud-init: OWLv2 backfill CPU-only resume (no GPU).
exec > >(tee /home/ubuntu/owlv2_backfill_userdata.log) 2>&1
set -euo pipefail
export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-owlv2-backfill}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION required}"
export DEVICE=cpu
export PATH=/usr/local/bin:$PATH

echo "=== owlv2_backfill userdata start (CPU) $(date -u) ==="
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
mkdir -p "$PIPE/data/posters" "$PIPE/aws" "$PIPE/data/qa/owlv2_backfill"

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

apt-get update -y || true
apt-get install -y python3 python3-pip python3-venv python3-full curl unzip ca-certificates || true

for i in $(seq 1 40); do
  if aws sts get-caller-identity >/dev/null 2>&1; then break; fi
  sleep 3
done
aws sts get-caller-identity || true

if aws s3 cp "s3://${BUCKET}/${PREFIX}/ENV" /tmp/owlv2_backfill_env 2>/dev/null; then
  set -a
  # shellcheck disable=SC1091
  source /tmp/owlv2_backfill_env
  set +a
fi
export DEVICE=cpu

echo "--- pull chain ---"
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/aws/owlv2_backfill_chain_cpu.sh" "$PIPE/aws/owlv2_backfill_chain_cpu.sh"
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/owlv2_creature_boxes.py" "$PIPE/owlv2_creature_boxes.py"
chmod +x "$PIPE/aws/owlv2_backfill_chain_cpu.sh"

chown -R ubuntu:ubuntu "$ROOT"
sudo -u ubuntu -H env \
  BUCKET="$BUCKET" PREFIX="$PREFIX" \
  AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
  SYNC_SECS="${SYNC_SECS:-180}" \
  CHECKPOINT_EVERY="${CHECKPOINT_EVERY:-25}" \
  DEVICE=cpu \
  OMP_NUM_THREADS=4 \
  MKL_NUM_THREADS=4 \
  PATH="/usr/local/bin:$PATH" \
  bash -lc "cd $PIPE && bash aws/owlv2_backfill_chain_cpu.sh"

echo "=== userdata done $(date -u) ==="
sudo shutdown -h now || true
