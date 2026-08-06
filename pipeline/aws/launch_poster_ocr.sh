#!/bin/bash
# Launch EC2 GPU instance for EasyOCR full-text (poster_ocr).
# Prerequisites: bash pipeline/aws/stage_poster_ocr.sh
#
# Usage:
#   bash pipeline/aws/launch_poster_ocr.sh
#   INSTANCE_TYPE=g4dn.xlarge bash pipeline/aws/launch_poster_ocr.sh
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

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa

# Default subnet: public subnet in an AZ that offers g4dn.xlarge
if [ -z "$SUBNET_ID" ]; then
  SUBNET_ID=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=vpc-00645f0b7c268861f" "Name=availability-zone,Values=us-east-1a" \
    --query 'Subnets[0].SubnetId' --output text)
fi

USERDATA="$PIPE/aws/poster_ocr_userdata.sh"
if [ ! -f "$USERDATA" ]; then
  echo "missing $USERDATA"; exit 1
fi

echo "=== launch poster_ocr ==="
echo "bucket=$BUCKET type=$INSTANCE_TYPE ami=$AMI_ID sg=$SG_ID subnet=$SUBNET_ID profile=$IAM_PROFILE"
echo "userdata=$USERDATA"

ARGS=(
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --user-data "file://$USERDATA"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=aof-poster-ocr},{Key=Project,Value=what-fear-looks-like}]"
  --instance-initiated-shutdown-behavior terminate
  --iam-instance-profile "Name=$IAM_PROFILE"
  --network-interfaces "DeviceIndex=0,SubnetId=${SUBNET_ID},Groups=${SG_ID},AssociatePublicIpAddress=${ASSOCIATE_PUBLIC_IP}"
)

if [ -n "$KEY_NAME" ]; then
  ARGS+=(--key-name "$KEY_NAME")
fi

IID=$(aws ec2 run-instances "${ARGS[@]}" --query 'Instances[0].InstanceId' --output text)
echo "$IID" | tee data/qa/poster_ocr_ec2.iid
echo "instance=$IID"
echo "waiting for public IP…"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "$IP" | tee data/qa/poster_ocr_ec2.ip
echo "LISTO — IP=$IP"
echo "Cuando termine: bash pipeline/aws/pull_poster_ocr.sh"
echo "Progreso: aws s3 ls s3://$BUCKET/metrics/poster_ocr_partial.csv"
