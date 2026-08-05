#!/bin/bash
# Launch workshop EC2 for Nova enrich (Bedrock direct).
# Prerequisites: stage already at s3://…/wflike-nova-enrich/cloud/ (posters + todo_ids).
#
# NOTE: us-west-2 SCP denies ec2:RunInstances / iam:PassRole for WSParticipantRole.
#       Launch in us-east-1 (same pattern as imdb/community jobs).
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/launch_nova_enrich_ec2.sh
#   LIMIT=3 bash pipeline/aws/launch_nova_enrich_ec2.sh   # smoke
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-nova-enrich/cloud}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.large}"
AMI_ID="${AMI_ID:-ami-052355af2a014bd2c}"
SG_ID="${SG_ID:-}"
SUBNET_ID="${SUBNET_ID:-}"
VPC_ID="${VPC_ID:-vpc-03b03e15ad07d5a31}"
IAM_PROFILE="${IAM_PROFILE:-wflike-ec2-train}"
KEY_NAME="${KEY_NAME:-}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
NAME_TAG="${NAME_TAG:-wflike-nova-enrich}"
WORKERS="${WORKERS:-4}"
MIN_INTERVAL="${MIN_INTERVAL:-0.55}"
LIMIT="${LIMIT:-0}"
BEDROCK_REGION="${BEDROCK_REGION:-us-east-1}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa

if [ -z "$SUBNET_ID" ]; then
  SUBNET_ID=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=availability-zone,Values=us-east-1a" \
    --query 'Subnets[0].SubnetId' --output text)
fi
if [ -z "$SG_ID" ]; then
  SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=group-name,Values=default" \
    --query 'SecurityGroups[0].GroupId' --output text)
fi

USERDATA="$PIPE/aws/nova_enrich_ec2_userdata.sh"
CHAIN="$PIPE/aws/nova_enrich_ec2_chain.sh"
RUNNER="$PIPE/nova_poster_enrich.py"
for f in "$USERDATA" "$CHAIN" "$RUNNER"; do
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
done

# Guard: do not touch unrelated jobs
echo "=== preflight: running instances (will not terminate any) ==="
aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=running,pending \
  --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Name`].Value|[0],InstanceType]' \
  --output text || true

echo "--- stage code + ENV ---"
cat > /tmp/nova_enrich_ENV <<EOF
export BUCKET=${BUCKET}
export PREFIX=${PREFIX}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
export BEDROCK_REGION=${BEDROCK_REGION}
export WORKERS=${WORKERS}
export MIN_INTERVAL=${MIN_INTERVAL}
export LIMIT=${LIMIT}
EOF
aws s3 cp /tmp/nova_enrich_ENV "s3://${BUCKET}/${PREFIX}/ENV"
aws s3 cp "$CHAIN" "s3://${BUCKET}/${PREFIX}/code/aws/nova_enrich_ec2_chain.sh"
aws s3 cp "$USERDATA" "s3://${BUCKET}/${PREFIX}/code/aws/nova_enrich_ec2_userdata.sh"
aws s3 cp "$RUNNER" "s3://${BUCKET}/${PREFIX}/code/nova_poster_enrich.py"

# Bake env into userdata (cloud-init cannot expand local env)
TMP_UD="$(mktemp /tmp/nova_enrich_ud.XXXXXX.sh)"
sed \
  -e "s|^export BUCKET=.*|export BUCKET=${BUCKET}|" \
  -e "s|^export PREFIX=.*|export PREFIX=${PREFIX}|" \
  -e "s|^export AWS_DEFAULT_REGION=.*|export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}|" \
  -e "s|^export BEDROCK_REGION=.*|export BEDROCK_REGION=${BEDROCK_REGION}|" \
  -e "s|^export WORKERS=.*|export WORKERS=${WORKERS}|" \
  -e "s|^export MIN_INTERVAL=.*|export MIN_INTERVAL=${MIN_INTERVAL}|" \
  -e "s|^export LIMIT=.*|export LIMIT=${LIMIT}|" \
  "$USERDATA" > "$TMP_UD"

echo "=== launch nova enrich EC2 ==="
echo "bucket=s3://$BUCKET/$PREFIX/ type=$INSTANCE_TYPE ami=$AMI_ID"
echo "sg=$SG_ID subnet=$SUBNET_ID profile=$IAM_PROFILE Name=$NAME_TAG"
echo "WORKERS=$WORKERS MIN_INTERVAL=$MIN_INTERVAL LIMIT=$LIMIT BEDROCK_REGION=$BEDROCK_REGION"

ARGS=(
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --user-data "file://${TMP_UD}"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=what-fear-looks-like},{Key=Job,Value=nova-enrich}]"
  --instance-initiated-shutdown-behavior terminate
  --iam-instance-profile "Name=${IAM_PROFILE}"
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":60,"VolumeType":"gp3","DeleteOnTermination":true}}]'
  --network-interfaces "DeviceIndex=0,SubnetId=${SUBNET_ID},Groups=${SG_ID},AssociatePublicIpAddress=${ASSOCIATE_PUBLIC_IP}"
)
if [ -n "$KEY_NAME" ]; then
  ARGS+=(--key-name "$KEY_NAME")
fi

IID=$(aws ec2 run-instances "${ARGS[@]}" --query 'Instances[0].InstanceId' --output text)
rm -f "$TMP_UD"
echo "$IID" | tee data/qa/nova_enrich_ec2.iid
echo "instance=$IID"
echo "waiting for running…"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "${IP:-none}" | tee data/qa/nova_enrich_ec2.ip
echo "LISTO — IID=$IID IP=${IP:-none} Name=$NAME_TAG"
echo "Monitor:  aws s3 ls s3://${BUCKET}/${PREFIX}/results/"
echo "Log:      aws s3 cp s3://${BUCKET}/${PREFIX}/results/nova_enrich_ec2.log -"
echo "Progress: aws s3 cp s3://${BUCKET}/${PREFIX}/progress_cloud.json -"
echo "Pull:     bash pipeline/aws/pull_nova_enrich_cloud.sh"
echo "(instance self-terminates when chain finishes)"
