#!/bin/bash
# Launch EC2 for vision-gap multi-pipeline backfill.
# Prerequisites: bash pipeline/aws/stage_vision_gap.sh
#
# Sandbox G/VT quota=0 → default CPU c5.4xlarge in us-east-1.
# Optional GPU: AWS_PROFILE=default INSTANCE_TYPE=g4dn.xlarge AMI_ID=... BUCKET=aof-owlv2-... (after staging posters).
#
# Does NOT terminate other jobs (OWL / IMDb / Comprehend / Nova).
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/launch_vision_gap.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy \
  no_proxy NO_PROXY || true

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-vision-gap}"
INSTANCE_TYPE="${INSTANCE_TYPE:-c5.9xlarge}"
AMI_ID="${AMI_ID:-ami-052355af2a014bd2c}"  # Ubuntu 24.04 us-east-1
SG_ID="${SG_ID:-}"
SUBNET_ID="${SUBNET_ID:-}"
VPC_ID="${VPC_ID:-vpc-03b03e15ad07d5a31}"
IAM_PROFILE="${IAM_PROFILE:-wflike-ec2-train}"
KEY_NAME="${KEY_NAME:-}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
NAME_TAG="${NAME_TAG:-wflike-vision-gap}"
VOLUME_GB="${VOLUME_GB:-150}"
POSTER_SRC="${POSTER_SRC:-s3://sagemaker-studio-a5572760/wflike-community-72k/posters}"
PROTECT_NAMES="${PROTECT_NAMES:-wflike-imdb-posters wflike-imdb-selenium wflike-owlv2-backfill wflike-community-72k wflike-nova-enrich}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa/vision_gap

case "$NAME_TAG" in
  wflike-imdb-posters|wflike-imdb-selenium|wflike-owlv2-backfill)
    echo "ERROR: refusing protected Name=$NAME_TAG"; exit 1 ;;
esac

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

USERDATA="$PIPE/aws/vision_gap_userdata.sh"
CHAIN="$PIPE/aws/vision_gap_chain.sh"
for f in "$USERDATA" "$CHAIN"; do
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
done

N_TODO=$(wc -l < data/qa/vision_gap/todo_ids.txt 2>/dev/null || echo 0)
echo "=== preflight: running instances (will not terminate) ==="
aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=running,pending \
  --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Name`].Value|[0],InstanceType]' \
  --output text || true

cat > /tmp/vision_gap_ENV <<EOF
export BUCKET=${BUCKET}
export PREFIX=${PREFIX}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
export POSTER_SRC=${POSTER_SRC}
export SYNC_SECS=${SYNC_SECS:-180}
export DL_WORKERS=${DL_WORKERS:-32}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-16}
export MKL_NUM_THREADS=${MKL_NUM_THREADS:-16}
export TORCH_NUM_THREADS=${TORCH_NUM_THREADS:-16}
EOF
aws s3 cp /tmp/vision_gap_ENV "s3://${BUCKET}/${PREFIX}/ENV"
aws s3 cp "$CHAIN" "s3://${BUCKET}/${PREFIX}/code/aws/vision_gap_chain.sh"
aws s3 cp "$USERDATA" "s3://${BUCKET}/${PREFIX}/code/aws/vision_gap_userdata.sh"

TMP_UD="$(mktemp /tmp/vision_gap_ud.XXXXXX.sh)"
sed \
  -e "s|^export BUCKET=.*|export BUCKET=${BUCKET}|" \
  -e "s|^export PREFIX=.*|export PREFIX=${PREFIX}|" \
  -e "s|^export AWS_DEFAULT_REGION=.*|export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}|" \
  -e "s|^export POSTER_SRC=.*|export POSTER_SRC=${POSTER_SRC}|" \
  "$USERDATA" > "$TMP_UD"

echo "=== launch vision_gap ==="
echo "bucket=s3://$BUCKET/$PREFIX/ type=$INSTANCE_TYPE ami=$AMI_ID vol=${VOLUME_GB}G"
echo "sg=$SG_ID subnet=$SUBNET_ID profile=$IAM_PROFILE Name=$NAME_TAG todo=$N_TODO"

ARGS=(
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --user-data "file://${TMP_UD}"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=what-fear-looks-like},{Key=Job,Value=vision-gap}]"
  --instance-initiated-shutdown-behavior terminate
  --iam-instance-profile "Name=${IAM_PROFILE}"
  --block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":${VOLUME_GB},\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true}}]"
  --network-interfaces "DeviceIndex=0,SubnetId=${SUBNET_ID},Groups=${SG_ID},AssociatePublicIpAddress=${ASSOCIATE_PUBLIC_IP}"
)
if [ -n "$KEY_NAME" ]; then
  ARGS+=(--key-name "$KEY_NAME")
fi

IID=$(aws ec2 run-instances "${ARGS[@]}" --query 'Instances[0].InstanceId' --output text)
rm -f "$TMP_UD"
echo "$IID" | tee data/qa/vision_gap/ec2.iid
echo "instance=$IID"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "${IP:-none}" | tee data/qa/vision_gap/ec2.ip

python3 <<PY
import json
from pathlib import Path
from datetime import datetime, timezone
qa = Path("data/qa/vision_gap")
gap = json.loads((qa / "gap_report.json").read_text()) if (qa / "gap_report.json").exists() else {}
doc = {
    "launched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "instance_id": "$IID",
    "public_ip": "${IP:-none}",
    "instance_type": "$INSTANCE_TYPE",
    "ami": "$AMI_ID",
    "name_tag": "$NAME_TAG",
    "bucket": "$BUCKET",
    "prefix": "$PREFIX",
    "region": "us-east-1",
    "iam_profile": "$IAM_PROFILE",
    "n_todo": int("$N_TODO"),
    "gap": gap,
    "pipelines": [
        "faces_v2", "attributes", "clip_embeddings",
        "census", "typography", "medium", "segmentation",
    ],
    "medium_path": "clip_medium.py (canonical medium.csv p_painted); Custom Labels not used (StartProjectVersion + different schema)",
    "gpu_note": "Sandbox G/VT On-Demand vCPU=0; CPU c5.9xlarge. Seg ~8-12h ETA for ~27k; clip_embed ~1h; faces+attrs ~2-4h.",
    "monitor": {
        "progress": f"aws s3 cp s3://$BUCKET/$PREFIX/results/PROGRESS.json -",
        "log": f"aws s3 cp s3://$BUCKET/$PREFIX/results/vision_gap_aws.log -",
        "ls": f"aws s3 ls s3://$BUCKET/$PREFIX/results/",
    },
    "pull": "AWS_PROFILE=sandbox bash pipeline/aws/pull_vision_gap.sh",
    "protect_names": "$PROTECT_NAMES".split(),
}
(qa / "launch.json").write_text(json.dumps(doc, indent=2) + "\n")
print(json.dumps(doc, indent=2))
PY

echo "LISTO — IID=$IID IP=${IP:-none} Name=$NAME_TAG todo=$N_TODO"
echo "Monitor:  aws s3 cp s3://${BUCKET}/${PREFIX}/results/PROGRESS.json -"
echo "Log:      aws s3 cp s3://${BUCKET}/${PREFIX}/results/vision_gap_aws.log -"
echo "Pull:     bash pipeline/aws/pull_vision_gap.sh"
