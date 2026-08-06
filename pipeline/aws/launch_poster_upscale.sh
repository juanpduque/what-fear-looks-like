#!/bin/bash
# Launch EC2 GPU for Real-ESRGAN poster upscale (width<1000 → x2).
# Prerequisites: bash aws/stage_poster_upscale.sh
#
#   bash aws/launch_poster_upscale.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-poster_upscale}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g4dn.xlarge}"
AMI_ID="${AMI_ID:-ami-0555989a7ddae85bb}"
SG_ID="${SG_ID:-sg-0271740ddc4db4415}"
SUBNET_ID="${SUBNET_ID:-}"
IAM_PROFILE="${IAM_PROFILE:-aof-owlv2-ec2}"
KEY_NAME="${KEY_NAME:-aof-owlv2}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
NAME_TAG="${NAME_TAG:-aof-poster-upscale}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa

if [ -z "$SUBNET_ID" ]; then
  SUBNET_ID=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=vpc-00645f0b7c268861f" "Name=availability-zone,Values=us-east-1a" \
    --query 'Subnets[0].SubnetId' --output text)
fi

USERDATA="$PIPE/aws/poster_upscale_userdata.sh"
chmod +x "$USERDATA" aws/poster_upscale_chain.sh aws/stage_poster_upscale.sh

N=$(wc -l < data/qa/posters_upscale_ids.txt | tr -d ' ')
echo "=== launch ${PREFIX} ==="
echo "bucket=$BUCKET type=$INSTANCE_TYPE n_ids=$N"

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
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "$IP" | tee "data/qa/${PREFIX}_ec2.ip"
echo "LISTO — IP=$IP instance=$IID"
echo "Monitor: aws s3 ls s3://$BUCKET/${PREFIX}/results/"
echo "Out:     aws s3 ls s3://$BUCKET/posters_original_up/ --summarize"
echo "SSH:     ssh -i ~/.ssh/aof-owlv2.pem ubuntu@$IP"
