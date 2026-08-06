#!/bin/bash
# Launch Spot g5.2xlarge for hard-set Kimi-VL OCR.
# Prerequisites: bash aws/stage_ocr_kimi_hard.sh
#
#   MODELS=kimi bash aws/launch_ocr_kimi_hard.sh
#   MARKET=on-demand bash aws/launch_ocr_kimi_hard.sh   # explicit on-demand
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_kimi_hard}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g5.2xlarge}"
AMI_ID="${AMI_ID:-ami-0555989a7ddae85bb}"
SG_ID="${SG_ID:-sg-0271740ddc4db4415}"
SUBNET_ID="${SUBNET_ID:-}"
IAM_PROFILE="${IAM_PROFILE:-aof-owlv2-ec2}"
KEY_NAME="${KEY_NAME:-aof-owlv2}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
MODELS="${MODELS:-kimi}"
NAME_TAG="${NAME_TAG:-aof-ocr-kimi-hard}"
MAX_N="${MAX_N:-120}"
MARKET="${MARKET:-spot}"  # spot | on-demand

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa

USERDATA="$PIPE/aws/ocr_kimi_hard_userdata.sh"
if [ ! -f "$USERDATA" ]; then
  echo "missing $USERDATA"; exit 1
fi

N_LOCAL=$(wc -l < "data/qa/${PREFIX}/sample_ids.txt" 2>/dev/null || echo 0)
if [ "$N_LOCAL" -gt "$MAX_N" ]; then
  echo "ERROR: sample_ids.txt has $N_LOCAL ids — must stay ≤$MAX_N"; exit 1
fi
if [ "$N_LOCAL" -lt 1 ]; then
  echo "ERROR: empty sample_ids.txt — run stage_ocr_kimi_hard.sh first"; exit 1
fi
if [ "$N_LOCAL" -ne 12 ]; then
  echo "WARNING: expected 12 hard ids, got $N_LOCAL (continuing)"
fi

# Don't collide with other OCR Name tags (crop uses aof-ocr-qwen-hard-crop)
EXISTING=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=${NAME_TAG}" \
            "Name=instance-state-name,Values=pending,running" \
  --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null || true)
if [ -n "${EXISTING// /}" ]; then
  echo "ERROR: already running with Name=$NAME_TAG: $EXISTING — refuse launch"
  exit 1
fi

printf '%s\n' "$MODELS" | aws s3 cp - "s3://${BUCKET}/${PREFIX}/MODELS"
echo "published MODELS=$MODELS → s3://${BUCKET}/${PREFIX}/MODELS"

# Spot capacity for g5 often misses us-east-1a; try several AZs (or forced SUBNET_ID)
VPC_ID="vpc-00645f0b7c268861f"
SPOT_AZS="${SPOT_AZS:-us-east-1b,us-east-1c,us-east-1d,us-east-1f,us-east-1a}"
resolve_subnet() {
  local az="$1"
  aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=availability-zone,Values=${az}" \
    --query 'Subnets[0].SubnetId' --output text
}

echo "=== launch ${PREFIX} ==="
echo "bucket=$BUCKET type=$INSTANCE_TYPE market=$MARKET ami=$AMI_ID sample_n=$N_LOCAL MODELS=$MODELS"

build_args() {
  local subnet="$1"
  ARGS=(
    --image-id "$AMI_ID"
    --instance-type "$INSTANCE_TYPE"
    --user-data "file://$USERDATA"
    --count 1
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=what-fear-looks-like},{Key=Market,Value=${MARKET}}]"
    --instance-initiated-shutdown-behavior terminate
    --iam-instance-profile "Name=$IAM_PROFILE"
    --network-interfaces "DeviceIndex=0,SubnetId=${subnet},Groups=${SG_ID},AssociatePublicIpAddress=${ASSOCIATE_PUBLIC_IP}"
    --block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":200,\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true}}]"
  )
  if [ -n "$KEY_NAME" ]; then
    ARGS+=(--key-name "$KEY_NAME")
  fi
  if [ "$MARKET" = "spot" ]; then
    ARGS+=(--instance-market-options '{"MarketType":"spot","SpotOptions":{"SpotInstanceType":"one-time","InstanceInterruptionBehavior":"terminate"}}')
  fi
}

launch_once() {
  local subnet="$1"
  build_args "$subnet"
  aws ec2 run-instances "${ARGS[@]}" --query 'Instances[0].InstanceId' --output text
}

IID=""
MARKET_USED="$MARKET"
AZ_USED=""
if [ -n "$SUBNET_ID" ]; then
  set +e
  IID=$(launch_once "$SUBNET_ID" 2>/tmp/ocr_kimi_hard_launch.err)
  rc=$?
  set -e
  if [ "$rc" -ne 0 ] || [ -z "$IID" ] || [ "$IID" = "None" ]; then
    echo "ERROR: launch failed on forced SUBNET_ID=$SUBNET_ID"
    cat /tmp/ocr_kimi_hard_launch.err 2>/dev/null | tail -40 || true
    exit 1
  fi
elif [ "$MARKET" = "spot" ]; then
  IFS=',' read -ra AZ_ARR <<< "$SPOT_AZS"
  for az in "${AZ_ARR[@]}"; do
    az=$(echo "$az" | tr -d ' ')
    [ -z "$az" ] && continue
    sn=$(resolve_subnet "$az")
    if [ -z "$sn" ] || [ "$sn" = "None" ]; then
      echo "skip AZ=$az (no subnet)"; continue
    fi
    echo "trying Spot AZ=$az subnet=$sn …"
    set +e
    IID=$(launch_once "$sn" 2>/tmp/ocr_kimi_hard_launch.err)
    rc=$?
    set -e
    if [ "$rc" -eq 0 ] && [ -n "$IID" ] && [ "$IID" != "None" ]; then
      AZ_USED="$az"
      SUBNET_ID="$sn"
      break
    fi
    echo "  Spot failed in $az (rc=$rc)"
    tail -5 /tmp/ocr_kimi_hard_launch.err 2>/dev/null || true
    IID=""
  done
  if [ -z "$IID" ] || [ "$IID" = "None" ]; then
    echo "ERROR: Spot unavailable in AZs [$SPOT_AZS] — NOT falling back to on-demand."
    echo "Re-run with MARKET=on-demand if you want on-demand explicitly."
    cat /tmp/ocr_kimi_hard_launch.err 2>/dev/null | tail -40 || true
    exit 1
  fi
else
  # on-demand: prefer us-east-1a then others
  for az in us-east-1a us-east-1b us-east-1c us-east-1d us-east-1f; do
    sn=$(resolve_subnet "$az")
    echo "trying on-demand AZ=$az subnet=$sn …"
    set +e
    IID=$(launch_once "$sn" 2>/tmp/ocr_kimi_hard_launch.err)
    rc=$?
    set -e
    if [ "$rc" -eq 0 ] && [ -n "$IID" ] && [ "$IID" != "None" ]; then
      AZ_USED="$az"
      SUBNET_ID="$sn"
      break
    fi
    IID=""
  done
  if [ -z "$IID" ] || [ "$IID" = "None" ]; then
    echo "ERROR: on-demand launch failed"
    cat /tmp/ocr_kimi_hard_launch.err 2>/dev/null | tail -40 || true
    exit 1
  fi
fi

echo "$IID" | tee "data/qa/${PREFIX}_ec2.iid"
echo "market_used=$MARKET_USED az=${AZ_USED:-forced}" | tee "data/qa/${PREFIX}_ec2.market"
echo "instance=$IID market=$MARKET_USED az=${AZ_USED:-?} subnet=$SUBNET_ID"
echo "waiting for public IP…"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "$IP" | tee "data/qa/${PREFIX}_ec2.ip"
# Confirm Spot lifecycle
LIFE=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].InstanceLifecycle' --output text 2>/dev/null || echo none)
PLACEMENT_AZ=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' --output text)
echo "InstanceLifecycle=${LIFE} AZ=${PLACEMENT_AZ}"
echo "LISTO — IP=$IP Name=$NAME_TAG MODELS=$MODELS market=$MARKET_USED lifecycle=$LIFE az=$PLACEMENT_AZ"
echo "Monitor:  aws s3 ls s3://$BUCKET/${PREFIX}/results/"
echo "Pull:     bash aws/pull_ocr_kimi_hard.sh"
echo "SSH:      ssh -i ~/.ssh/aof-owlv2.pem ubuntu@$IP"
