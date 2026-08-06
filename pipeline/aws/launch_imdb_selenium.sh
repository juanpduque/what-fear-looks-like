#!/bin/bash
# Launch workshop EC2 for IMDb Selenium (headed Chrome + Xvfb).
# Prerequisites: bash pipeline/aws/stage_imdb_selenium.sh
#
# Sandbox defaults (AWS_PROFILE=sandbox):
#   BUCKET=sagemaker-studio-a5572760
#   IAM=wflike-ec2-train
#   VPC default + public subnet
#   Ubuntu 24.04 + t3.large (CPU; no GPU needed)
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/stage_imdb_selenium.sh
#   bash pipeline/aws/launch_imdb_selenium.sh
#   MODE=ambiguous LIMIT=5 bash pipeline/aws/launch_imdb_selenium.sh
#   INSTANCE_TYPE=t3.xlarge bash pipeline/aws/launch_imdb_selenium.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-imdb-selenium}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.large}"
# Ubuntu Server 24.04 LTS amd64 (us-east-1) — override if retired
AMI_ID="${AMI_ID:-ami-052355af2a014bd2c}"
SG_ID="${SG_ID:-}"
SUBNET_ID="${SUBNET_ID:-}"
VPC_ID="${VPC_ID:-vpc-03b03e15ad07d5a31}"
IAM_PROFILE="${IAM_PROFILE:-wflike-ec2-train}"
KEY_NAME="${KEY_NAME:-}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
MODE="${MODE:-features}"
LIMIT="${LIMIT:-0}"
DELAY="${DELAY:-1.4}"
NAME_TAG="${NAME_TAG:-wflike-imdb-selenium}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa

if [ -z "$SUBNET_ID" ]; then
  SUBNET_ID=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=availability-zone,Values=us-east-1a" \
    --query 'Subnets[0].SubnetId' --output text)
fi

if [ -z "$SG_ID" ]; then
  # default SG of the VPC (outbound OK; SSH optional)
  SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=group-name,Values=default" \
    --query 'SecurityGroups[0].GroupId' --output text)
fi

USERDATA="$PIPE/aws/imdb_selenium_userdata.sh"
if [ ! -f "$USERDATA" ]; then
  echo "missing $USERDATA"; exit 1
fi

# Refresh ENV on S3 so userdata picks MODE/LIMIT without re-staging code
cat > /tmp/imdb_selenium_ENV <<EOF
export BUCKET=${BUCKET}
export PREFIX=${PREFIX}
export MODE=${MODE}
export LIMIT=${LIMIT}
export DELAY=${DELAY}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
EOF
aws s3 cp /tmp/imdb_selenium_ENV "s3://${BUCKET}/${PREFIX}/ENV"
# Ensure userdata script is current
aws s3 cp "$USERDATA" "s3://${BUCKET}/${PREFIX}/code/aws/imdb_selenium_userdata.sh"
aws s3 cp "$PIPE/aws/imdb_selenium_chain.sh" "s3://${BUCKET}/${PREFIX}/code/aws/imdb_selenium_chain.sh"

# Bake bucket/prefix into a temp userdata (cloud-init cannot expand local env)
TMP_UD="$(mktemp /tmp/imdb_selenium_ud.XXXXXX.sh)"
sed \
  -e "s|^export BUCKET=.*|export BUCKET=${BUCKET}|" \
  -e "s|^export PREFIX=.*|export PREFIX=${PREFIX}|" \
  -e "s|^export MODE=.*|export MODE=${MODE}|" \
  -e "s|^export LIMIT=.*|export LIMIT=${LIMIT}|" \
  -e "s|^export DELAY=.*|export DELAY=${DELAY}|" \
  "$USERDATA" > "$TMP_UD"

echo "=== launch imdb_selenium ==="
echo "bucket=s3://$BUCKET/$PREFIX/ type=$INSTANCE_TYPE ami=$AMI_ID"
echo "sg=$SG_ID subnet=$SUBNET_ID profile=$IAM_PROFILE Name=$NAME_TAG"
echo "MODE=$MODE LIMIT=$LIMIT DELAY=$DELAY"

ARGS=(
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --user-data "file://${TMP_UD}"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=what-fear-looks-like},{Key=Job,Value=imdb-selenium}]"
  --instance-initiated-shutdown-behavior terminate
  --iam-instance-profile "Name=${IAM_PROFILE}"
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":40,"VolumeType":"gp3","DeleteOnTermination":true}}]'
  --network-interfaces "DeviceIndex=0,SubnetId=${SUBNET_ID},Groups=${SG_ID},AssociatePublicIpAddress=${ASSOCIATE_PUBLIC_IP}"
)

if [ -n "$KEY_NAME" ]; then
  ARGS+=(--key-name "$KEY_NAME")
fi

IID=$(aws ec2 run-instances "${ARGS[@]}" --query 'Instances[0].InstanceId' --output text)
rm -f "$TMP_UD"
echo "$IID" | tee data/qa/imdb_selenium_ec2.iid
echo "instance=$IID"
echo "waiting for running…"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "${IP:-none}" | tee data/qa/imdb_selenium_ec2.ip
echo "LISTO — IID=$IID IP=${IP:-none} Name=$NAME_TAG"
echo "Monitor:  aws s3 ls s3://${BUCKET}/${PREFIX}/results/"
echo "Pull:     bash pipeline/aws/pull_imdb_selenium.sh"
echo "(instance self-terminates when chain finishes)"
