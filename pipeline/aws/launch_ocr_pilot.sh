#!/bin/bash
# Launch EC2 GPU instance for OCR model pilot (small sample only).
# Prerequisites: bash pipeline/aws/stage_ocr_pilot.sh
#
# Usage:
#   bash pipeline/aws/launch_ocr_pilot.sh
#   INSTANCE_TYPE=g4dn.xlarge bash pipeline/aws/launch_ocr_pilot.sh
#   MODELS=deepseek,paddle,qwen NAME_TAG=aof-ocr-pilot-retry bash pipeline/aws/launch_ocr_pilot.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-aof-owlv2-102516364259}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g4dn.xlarge}"
# Deep Learning OSS Nvidia Driver AMI GPU PyTorch (Ubuntu 24.04) — override if retired
AMI_ID="${AMI_ID:-ami-0555989a7ddae85bb}"
SG_ID="${SG_ID:-sg-0271740ddc4db4415}"
SUBNET_ID="${SUBNET_ID:-}"
IAM_PROFILE="${IAM_PROFILE:-aof-owlv2-ec2}"
KEY_NAME="${KEY_NAME:-aof-owlv2}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
MODELS="${MODELS:-got,deepseek,paddle,qianfan,qwen}"
NAME_TAG="${NAME_TAG:-aof-ocr-pilot}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa

# Default subnet: public subnet in an AZ that offers g4dn.xlarge
if [ -z "$SUBNET_ID" ]; then
  SUBNET_ID=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=vpc-00645f0b7c268861f" "Name=availability-zone,Values=us-east-1a" \
    --query 'Subnets[0].SubnetId' --output text)
fi

USERDATA="$PIPE/aws/ocr_pilot_userdata.sh"
if [ ! -f "$USERDATA" ]; then
  echo "missing $USERDATA"; exit 1
fi

# Guard: refuse launch if sample looks like full corpus
N_LOCAL=$(wc -l < data/qa/ocr_pilot/sample_ids.txt 2>/dev/null || echo 0)
if [ "$N_LOCAL" -gt 80 ]; then
  echo "ERROR: sample_ids.txt has $N_LOCAL ids — pilot must stay ≤80"; exit 1
fi

# Publish MODELS for the chain (userdata does not expand local env)
printf '%s\n' "$MODELS" | aws s3 cp - "s3://${BUCKET}/ocr_pilot/MODELS"
echo "published MODELS=$MODELS → s3://${BUCKET}/ocr_pilot/MODELS"

echo "=== launch ocr_pilot ==="
echo "bucket=$BUCKET type=$INSTANCE_TYPE ami=$AMI_ID sg=$SG_ID subnet=$SUBNET_ID profile=$IAM_PROFILE"
echo "userdata=$USERDATA sample_n=$N_LOCAL MODELS=$MODELS Name=$NAME_TAG"

ARGS=(
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --user-data "file://$USERDATA"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=what-fear-looks-like}]"
  --instance-initiated-shutdown-behavior terminate
  --iam-instance-profile "Name=$IAM_PROFILE"
  --network-interfaces "DeviceIndex=0,SubnetId=${SUBNET_ID},Groups=${SG_ID},AssociatePublicIpAddress=${ASSOCIATE_PUBLIC_IP}"
)

if [ -n "$KEY_NAME" ]; then
  ARGS+=(--key-name "$KEY_NAME")
fi

IID=$(aws ec2 run-instances "${ARGS[@]}" --query 'Instances[0].InstanceId' --output text)
echo "$IID" | tee data/qa/ocr_pilot_ec2.iid
echo "instance=$IID"
echo "waiting for public IP…"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "$IP" | tee data/qa/ocr_pilot_ec2.ip
echo "LISTO — IP=$IP Name=$NAME_TAG MODELS=$MODELS"
echo "Monitor:  aws s3 ls s3://$BUCKET/ocr_pilot/results/"
echo "Pull:     bash pipeline/aws/pull_ocr_pilot.sh"
echo "SSH:      ssh -i ~/.ssh/aof-owlv2.pem ubuntu@$IP"
