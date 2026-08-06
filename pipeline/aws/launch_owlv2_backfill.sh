#!/bin/bash
# Launch g4dn GPU for OWLv2 creature backfill + weapon detection.
# Prerequisites: bash pipeline/aws/stage_owlv2_backfill.sh
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/launch_owlv2_backfill.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

# Defaults: aof account (GPU quota). Sandbox workshop has G/VT vCPU=0.
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-wflike-owlv2-backfill}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g4dn.xlarge}"
# Deep Learning OSS Nvidia Driver AMI GPU PyTorch (Ubuntu 24.04)
AMI_ID="${AMI_ID:-ami-0555989a7ddae85bb}"
SG_ID="${SG_ID:-sg-0271740ddc4db4415}"
SUBNET_ID="${SUBNET_ID:-}"
VPC_ID="${VPC_ID:-vpc-00645f0b7c268861f}"
IAM_PROFILE="${IAM_PROFILE:-aof-owlv2-ec2}"
KEY_NAME="${KEY_NAME:-aof-owlv2}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
NAME_TAG="${NAME_TAG:-wflike-owlv2-backfill}"
# Do not touch sandbox IMDb posters job (different account; listed for docs)
PROTECT_IIDS="${PROTECT_IIDS:-i-0d70c936e1e39759b}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa/owlv2_backfill

# Refuse CPU-only launches for this job (user requires GPU)
case "$INSTANCE_TYPE" in
  t3*|t2*|c5*|c6*|m5*|m6*|r5*|r6*)
    echo "ERROR: refusing CPU instance type $INSTANCE_TYPE — use g4dn.xlarge"; exit 1 ;;
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

USERDATA="$PIPE/aws/owlv2_backfill_userdata.sh"
if [ ! -f "$USERDATA" ]; then
  echo "missing $USERDATA"; exit 1
fi

N_IDS=$(wc -l < data/qa/owlv2_backfill/backfill_ids.txt 2>/dev/null || echo 0)
if [ "$N_IDS" -lt 1000 ]; then
  echo "ERROR: backfill_ids.txt has $N_IDS ids — run stage_owlv2_backfill.sh first"; exit 1
fi

for bad in $PROTECT_IIDS; do
  if [ "$NAME_TAG" = "wflike-imdb-posters" ] || [ "$NAME_TAG" = "wflike-imdb-selenium" ]; then
    echo "ERROR: refusing Name=$NAME_TAG (protected job family)"; exit 1
  fi
done

cat > /tmp/owlv2_backfill_ENV <<EOF
export BUCKET=${BUCKET}
export PREFIX=${PREFIX}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
export SYNC_SECS=180
export CHECKPOINT_EVERY=25
export DEVICE=cuda
EOF
aws s3 cp /tmp/owlv2_backfill_ENV "s3://${BUCKET}/${PREFIX}/ENV"
aws s3 cp "$USERDATA" "s3://${BUCKET}/${PREFIX}/code/aws/owlv2_backfill_userdata.sh"
aws s3 cp "$PIPE/aws/owlv2_backfill_chain.sh" "s3://${BUCKET}/${PREFIX}/code/aws/owlv2_backfill_chain.sh"
aws s3 cp "$PIPE/owlv2_creature_boxes.py" "s3://${BUCKET}/${PREFIX}/code/owlv2_creature_boxes.py"

TMP_UD="$(mktemp /tmp/owlv2_backfill_ud.XXXXXX)"
sed \
  -e "s|^export BUCKET=.*|export BUCKET=${BUCKET}|" \
  -e "s|^export PREFIX=.*|export PREFIX=${PREFIX}|" \
  "$USERDATA" > "$TMP_UD"

echo "=== launch owlv2_backfill (GPU) ==="
echo "bucket=s3://$BUCKET/$PREFIX/ type=$INSTANCE_TYPE ami=$AMI_ID"
echo "sg=$SG_ID subnet=$SUBNET_ID profile=$IAM_PROFILE Name=$NAME_TAG ids=$N_IDS"
echo "protect_instances=$PROTECT_IIDS DEVICE=cuda"

ARGS=(
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --user-data "file://${TMP_UD}"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=what-fear-looks-like},{Key=Job,Value=owlv2-backfill}]"
  --instance-initiated-shutdown-behavior terminate
  --iam-instance-profile "Name=$IAM_PROFILE"
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":100,"VolumeType":"gp3","DeleteOnTermination":true}}]'
  --network-interfaces "DeviceIndex=0,SubnetId=${SUBNET_ID},Groups=${SG_ID},AssociatePublicIpAddress=${ASSOCIATE_PUBLIC_IP}"
)

if [ -n "$KEY_NAME" ]; then
  ARGS+=(--key-name "$KEY_NAME")
fi

IID=$(aws ec2 run-instances "${ARGS[@]}" --query 'Instances[0].InstanceId' --output text)
rm -f "$TMP_UD"
echo "$IID" | tee data/qa/owlv2_backfill/ec2.iid
echo "instance=$IID"
echo "waiting for running…"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "${IP:-none}" | tee data/qa/owlv2_backfill/ec2.ip

python3 <<PY
import json
from pathlib import Path
from datetime import datetime, timezone
qa = Path("data/qa/owlv2_backfill")
meta = json.loads((qa / "backfill_meta.json").read_text()) if (qa / "backfill_meta.json").exists() else {}
doc = {
    "launched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "instance_id": "$IID",
    "public_ip": "${IP:-none}",
    "instance_type": "$INSTANCE_TYPE",
    "ami": "$AMI_ID",
    "name_tag": "$NAME_TAG",
    "compute": "gpu",
    "device": "cuda",
    "bucket": "$BUCKET",
    "prefix": "$PREFIX",
    "aws_profile": "default",
    "aws_account": "102516364259",
    "region": "us-east-1",
    "iam_profile": "$IAM_PROFILE",
    "n_ids": int("$N_IDS"),
    "sandbox_note": "Workshop sandbox (567596065542) has G/VT On-Demand vCPU=0; launched on aof account with GPU quota 8",
    "meta": meta,
    "creature_queries": [
        "vampire","werewolf","zombie","ghost","demon","witch","skeleton","alien",
        "giant_monster","masked_killer","clown","doll","shark","spider","snake",
        "wolf_dog","bird","insect"
    ],
    "weapon_queries": [
        "knife","gun","rifle","axe","sword","machete","chainsaw","scissors",
        "syringe","hammer","baseball_bat","arrow"
    ],
    "outputs": {
        "creature_delta": f"s3://$BUCKET/$PREFIX/results/creature_boxes_delta.json",
        "weapon_boxes": f"s3://$BUCKET/$PREFIX/results/weapon_boxes.json",
        "progress": f"s3://$BUCKET/$PREFIX/results/PROGRESS",
        "done": f"s3://$BUCKET/$PREFIX/results/DONE",
        "log": f"s3://$BUCKET/$PREFIX/results/owlv2_backfill_aws.log",
    },
    "eta_hours_rough": round(int("$N_IDS") * 1.5 / 3600, 1),
    "eta_note": "~1–2 s/img on g4dn.xlarge with 30 text queries; ~8–11h for ~19k",
    "protect_instances": "$PROTECT_IIDS".split(),
    "terminated_wrong_cpu_instance": "i-09b2695738e357e3f",
    "monitor": f"AWS_PROFILE=sandbox aws s3 cp s3://$BUCKET/$PREFIX/results/PROGRESS -",
    "pull_merge": "AWS_PROFILE=sandbox bash pipeline/aws/pull_owlv2_backfill.sh",
}
(qa / "launch.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print(json.dumps(doc, indent=2))
PY

echo "LISTO — IID=$IID IP=${IP:-none} Name=$NAME_TAG DEVICE=cuda type=$INSTANCE_TYPE"
echo "Monitor:  AWS_PROFILE=default aws s3 cp s3://${BUCKET}/${PREFIX}/results/PROGRESS -"
echo "Pull:     AWS_PROFILE=default bash pipeline/aws/pull_owlv2_backfill.sh"
echo "(instance self-terminates when chain finishes; do not touch sandbox IMDb posters jobs)"
