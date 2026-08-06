#!/bin/bash
# cloud-init: OWLv2 creature backfill + weapons on Deep Learning GPU AMI.
# Defaults match AWS_PROFILE=sandbox workshop account.
exec > >(tee /home/ubuntu/owlv2_backfill_userdata.log) 2>&1
set -euo pipefail
export BUCKET="${BUCKET:-aof-owlv2-102516364259}"
export PREFIX="${PREFIX:-wflike-owlv2-backfill}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH
export DEVICE="${DEVICE:-cuda}"

echo "=== owlv2_backfill userdata start (GPU) $(date -u) ==="
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
  apt-get install -y curl unzip ca-certificates
  tmp="$(mktemp -d)"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "$tmp/awscliv2.zip"
  unzip -q "$tmp/awscliv2.zip" -d "$tmp"
  "$tmp/aws/install" -i /usr/local/aws-cli -b /usr/local/bin
  rm -rf "$tmp"
  hash -r || true
  export PATH=/usr/local/bin:$PATH
}
ensure_aws_cli

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

echo "--- pull chain ---"
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/aws/owlv2_backfill_chain.sh" "$PIPE/aws/owlv2_backfill_chain.sh"
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/owlv2_creature_boxes.py" "$PIPE/owlv2_creature_boxes.py"
chmod +x "$PIPE/aws/owlv2_backfill_chain.sh"

chown -R ubuntu:ubuntu "$ROOT"
sudo -u ubuntu -H env \
  BUCKET="$BUCKET" PREFIX="$PREFIX" \
  AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
  SYNC_SECS="${SYNC_SECS:-180}" \
  CHECKPOINT_EVERY="${CHECKPOINT_EVERY:-25}" \
  DEVICE="${DEVICE:-cuda}" \
  PATH="/opt/pytorch/bin:/usr/local/bin:$PATH" \
  HF_HOME=/home/ubuntu/.cache/huggingface \
  bash -lc "cd $PIPE && bash aws/owlv2_backfill_chain.sh"

echo "=== userdata done $(date -u) ==="
