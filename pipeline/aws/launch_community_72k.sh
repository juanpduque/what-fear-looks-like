#!/bin/bash
# Launch EC2 for community-72k TMDB enumerate + S3 posters + Rekognition.
# Prerequisites: bash pipeline/aws/stage_community_72k.sh
#
# Does NOT touch protected instances:
#   i-0d70c936e1e39759b (IMDb posters), i-0f04b405308589396 (features), OWL jobs
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/launch_community_72k.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy \
  no_proxy NO_PROXY || true

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-community-72k}"
INSTANCE_TYPE="${INSTANCE_TYPE:-c5.xlarge}"
AMI_ID="${AMI_ID:-ami-052355af2a014bd2c}"  # Ubuntu 24.04 us-east-1
SG_ID="${SG_ID:-}"
SUBNET_ID="${SUBNET_ID:-}"
VPC_ID="${VPC_ID:-vpc-03b03e15ad07d5a31}"
IAM_PROFILE="${IAM_PROFILE:-wflike-ec2-train}"
KEY_NAME="${KEY_NAME:-}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
NAME_TAG="${NAME_TAG:-wflike-community-72k}"
PROTECT_IIDS="${PROTECT_IIDS:-i-0d70c936e1e39759b i-0f04b405308589396}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa/community_72k

# Refuse dangerous name collisions
case "$NAME_TAG" in
  wflike-imdb-posters|wflike-imdb-selenium|wflike-owlv2-backfill)
    echo "ERROR: refusing Name=$NAME_TAG (protected job family)"; exit 1 ;;
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

USERDATA="$PIPE/aws/community_72k_userdata.sh"
[ -f "$USERDATA" ] || { echo "missing $USERDATA"; exit 1; }

# Ensure ENV + userdata on S3
cat > /tmp/community_72k_ENV <<EOF
export BUCKET=${BUCKET}
export PREFIX=${PREFIX}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
export DOWNLOAD_WORKERS=${DOWNLOAD_WORKERS:-24}
export REK_WORKERS=${REK_WORKERS:-10}
export MIN_INTERVAL=${MIN_INTERVAL:-0.04}
export SAVE_EVERY=${SAVE_EVERY:-25}
export SYNC_SECS=${SYNC_SECS:-120}
EOF
aws s3 cp /tmp/community_72k_ENV "s3://${BUCKET}/${PREFIX}/ENV"
aws s3 cp "$USERDATA" "s3://${BUCKET}/${PREFIX}/code/aws/community_72k_userdata.sh"
aws s3 cp "$PIPE/aws/community_72k_chain.sh" "s3://${BUCKET}/${PREFIX}/code/aws/community_72k_chain.sh"
aws s3 cp "$PIPE/tmdb_enumerate_horror.py" "s3://${BUCKET}/${PREFIX}/code/tmdb_enumerate_horror.py"
aws s3 cp "$PIPE/community_72k_aws_worker.py" "s3://${BUCKET}/${PREFIX}/code/community_72k_aws_worker.py"

TMP_UD="$(mktemp /tmp/community_72k_ud.XXXXXX.sh)"
sed \
  -e "s|^export BUCKET=.*|export BUCKET=${BUCKET}|" \
  -e "s|^export PREFIX=.*|export PREFIX=${PREFIX}|" \
  "$USERDATA" > "$TMP_UD"

echo "=== launch community_72k ==="
echo "bucket=s3://$BUCKET/$PREFIX/ type=$INSTANCE_TYPE ami=$AMI_ID"
echo "sg=$SG_ID subnet=$SUBNET_ID profile=$IAM_PROFILE Name=$NAME_TAG"
echo "protect=$PROTECT_IIDS"

ARGS=(
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --user-data "file://${TMP_UD}"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=what-fear-looks-like},{Key=Job,Value=community-72k}]"
  --instance-initiated-shutdown-behavior terminate
  --iam-instance-profile "Name=$IAM_PROFILE"
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":40,"VolumeType":"gp3","DeleteOnTermination":true}}]'
  --network-interfaces "DeviceIndex=0,SubnetId=${SUBNET_ID},Groups=${SG_ID},AssociatePublicIpAddress=${ASSOCIATE_PUBLIC_IP}"
)
if [ -n "$KEY_NAME" ]; then
  ARGS+=(--key-name "$KEY_NAME")
fi

IID=$(aws ec2 run-instances "${ARGS[@]}" --query 'Instances[0].InstanceId' --output text)
rm -f "$TMP_UD"
echo "$IID" | tee data/qa/community_72k/ec2.iid
echo "instance=$IID"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "${IP:-none}" | tee data/qa/community_72k/ec2.ip

SKIP_LABELS=0
SKIP_TEXT=0
if [ -f data/qa/community_72k/skip_meta.json ]; then
  SKIP_LABELS=$(python3 -c "import json; print(json.load(open('data/qa/community_72k/skip_meta.json')).get('skip_labels',0))")
  SKIP_TEXT=$(python3 -c "import json; print(json.load(open('data/qa/community_72k/skip_meta.json')).get('skip_detecttext',0))")
fi

python3 <<PY
import json
from pathlib import Path
from datetime import datetime, timezone

qa = Path("data/qa/community_72k")
skip = {}
sp = qa / "skip_meta.json"
if sp.exists():
    skip = json.loads(sp.read_text())

# Rough cost: Labels suite ≈ \$0.003/img (3 Group-2 calls), DetectText ≈ \$0.001/img
n_target = 72531
skip_l = int(skip.get("skip_labels", 0))
skip_t = int(skip.get("skip_detecttext", 0))
est_labels = max(0, n_target - skip_l)
est_text = max(0, n_target - skip_t)
# Not all have posters — assume ~90% have poster_path
poster_frac = 0.90
est_labels = int(est_labels * poster_frac)
est_text = int(est_text * poster_frac)
cost_labels = est_labels * 0.003
cost_text = est_text * 0.001
# Rate ~3 img/s labels suite on c5.xlarge with workers=10 → ~0.33 posters/s wall
eta_labels_h = est_labels / 3.0 / 3600
eta_text_h = est_text / 5.0 / 3600
eta_enum_h = 1.5
eta_dl_h = 2.0

doc = {
    "launched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "status": "running",
    "instance_id": "$IID",
    "public_ip": "${IP:-none}",
    "instance_type": "$INSTANCE_TYPE",
    "ami": "$AMI_ID",
    "name_tag": "$NAME_TAG",
    "bucket": "$BUCKET",
    "prefix": "$PREFIX",
    "s3_root": f"s3://$BUCKET/$PREFIX/",
    "aws_profile": "sandbox",
    "region": "us-east-1",
    "iam_profile": "$IAM_PROFILE",
    "protect_instances": "$PROTECT_IIDS".split(),
    "skip": skip,
    "pipeline": [
        "enumerate TMDB horror (year-sharded Discover) → results/tmdb_horror_ids.csv",
        "download posters with poster_path → posters/{id}.jpg on S3 (skip existing)",
        "Rekognition Labels+IP+Mod+Faces for ids not in skip_labels",
        "Rekognition DetectText for ids not in skip_detecttext",
    ],
    "outputs": {
        "ids": f"s3://$BUCKET/$PREFIX/results/tmdb_horror_ids.csv",
        "posters": f"s3://$BUCKET/$PREFIX/posters/",
        "labels": f"s3://$BUCKET/$PREFIX/results/rekognition_community_72k.csv",
        "detecttext": f"s3://$BUCKET/$PREFIX/results/detecttext_community_72k.csv",
        "progress": f"s3://$BUCKET/$PREFIX/results/PROGRESS.json",
        "log": f"s3://$BUCKET/$PREFIX/results/community_72k_aws.log",
        "done": f"s3://$BUCKET/$PREFIX/results/DONE",
    },
    "cost_eta": {
        "target_ids": n_target,
        "est_labels_todo": est_labels,
        "est_detecttext_todo": est_text,
        "est_cost_usd_labels": round(cost_labels, 2),
        "est_cost_usd_detecttext": round(cost_text, 2),
        "est_cost_usd_total_rek": round(cost_labels + cost_text, 2),
        "est_hours_enumerate": eta_enum_h,
        "est_hours_download": eta_dl_h,
        "est_hours_labels": round(eta_labels_h, 1),
        "est_hours_detecttext": round(eta_text_h, 1),
        "est_hours_total": round(eta_enum_h + eta_dl_h + eta_labels_h + eta_text_h, 1),
        "sandbox_warning": (
            "Full Labels suite on ~72k is ~\$200–270 if nothing skipped; "
            f"with skip_labels={skip_l} remaining Labels≈\${cost_labels:.0f}. "
            "Ephemeral workshop sandbox may die before finish — S3 checkpoints are resume-safe; re-launch same PREFIX."
        ),
    },
    "monitor": [
        f"AWS_PROFILE=sandbox aws s3 cp s3://$BUCKET/$PREFIX/results/PROGRESS.json -",
        f"AWS_PROFILE=sandbox aws s3 cp s3://$BUCKET/$PREFIX/results/community_72k_aws.log - | tail -40",
        f"AWS_PROFILE=sandbox aws ec2 describe-instances --instance-ids $IID --query 'Reservations[0].Instances[0].State.Name'",
    ],
    "pull_later": "AWS_PROFILE=sandbox bash pipeline/aws/pull_community_72k.sh",
    "no_local_posters": True,
    "note": "No mass poster download to Mac. Artifacts live on S3 until user pulls.",
}
(qa / "launch.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
# Also write the required status path
Path("data/qa").mkdir(parents=True, exist_ok=True)
Path("data/qa/community_72k_rekognition_status.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print(json.dumps(doc, indent=2))
PY

echo "LISTO — IID=$IID IP=${IP:-none} Name=$NAME_TAG"
echo "Monitor: AWS_PROFILE=sandbox aws s3 cp s3://${BUCKET}/${PREFIX}/results/PROGRESS.json -"
echo "Status:  pipeline/data/qa/community_72k_rekognition_status.json"
echo "(protected instances untouched: $PROTECT_IIDS)"
