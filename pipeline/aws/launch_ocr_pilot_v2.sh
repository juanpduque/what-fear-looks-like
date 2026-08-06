#!/bin/bash
# Launch EC2 GPU for OCR pilot v2 (n≈100 VLMs).
# Prerequisites: bash aws/stage_ocr_pilot_v2.sh
#
#   MODELS=qwen,deepseek,paddle,qianfan,got bash aws/launch_ocr_pilot_v2.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_pilot_v2}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g4dn.xlarge}"
AMI_ID="${AMI_ID:-ami-0555989a7ddae85bb}"
SG_ID="${SG_ID:-sg-0271740ddc4db4415}"
SUBNET_ID="${SUBNET_ID:-}"
IAM_PROFILE="${IAM_PROFILE:-aof-owlv2-ec2}"
KEY_NAME="${KEY_NAME:-aof-owlv2}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
MODELS="${MODELS:-qwen,deepseek,paddle,qianfan,got}"
NAME_TAG="${NAME_TAG:-aof-ocr-pilot-v2}"
MAX_N="${MAX_N:-120}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa

if [ -z "$SUBNET_ID" ]; then
  SUBNET_ID=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=vpc-00645f0b7c268861f" "Name=availability-zone,Values=us-east-1a" \
    --query 'Subnets[0].SubnetId' --output text)
fi

USERDATA="$PIPE/aws/ocr_pilot_v2_userdata.sh"
if [ ! -f "$USERDATA" ]; then
  echo "missing $USERDATA"; exit 1
fi

N_LOCAL=$(wc -l < "data/qa/${PREFIX}/sample_ids.txt" 2>/dev/null || echo 0)
if [ "$N_LOCAL" -gt "$MAX_N" ]; then
  echo "ERROR: sample_ids.txt has $N_LOCAL ids — must stay ≤$MAX_N"; exit 1
fi
if [ "$N_LOCAL" -lt 1 ]; then
  echo "ERROR: empty sample_ids.txt"; exit 1
fi

printf '%s\n' "$MODELS" | aws s3 cp - "s3://${BUCKET}/${PREFIX}/MODELS"
echo "published MODELS=$MODELS → s3://${BUCKET}/${PREFIX}/MODELS"

echo "=== launch ${PREFIX} ==="
echo "bucket=$BUCKET type=$INSTANCE_TYPE ami=$AMI_ID sample_n=$N_LOCAL MODELS=$MODELS"

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
echo "$IID" | tee "data/qa/${PREFIX}_ec2.iid"
echo "instance=$IID"
echo "waiting for public IP…"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "$IP" | tee "data/qa/${PREFIX}_ec2.ip"
echo "LISTO — IP=$IP Name=$NAME_TAG MODELS=$MODELS"
echo "Monitor:  aws s3 ls s3://$BUCKET/${PREFIX}/results/"
echo "Pull:     bash aws/pull_ocr_pilot_v2.sh"
echo "SSH:      ssh -i ~/.ssh/aof-owlv2.pem ubuntu@$IP"
