#!/bin/bash
# Launch EC2 for Rekognition Custom Labels full-set inference (medium clf).
# StartProjectVersion is deferred to the EC2 chain (right before DetectCustomLabels)
# unless START_MODEL_AT_LAUNCH=1 — avoids idle IU billing during apt/boot.
#
# Does NOT terminate vision / nova / owl / comprehend jobs.
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/launch_custom_labels_infer.sh
#   LIMIT=500 bash pipeline/aws/launch_custom_labels_infer.sh   # smoke
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN || true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy \
  no_proxy NO_PROXY || true

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-custom-labels/infer}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.large}"
AMI_ID="${AMI_ID:-ami-052355af2a014bd2c}"
SG_ID="${SG_ID:-}"
SUBNET_ID="${SUBNET_ID:-}"
VPC_ID="${VPC_ID:-vpc-03b03e15ad07d5a31}"
IAM_PROFILE="${IAM_PROFILE:-wflike-ec2-train}"
KEY_NAME="${KEY_NAME:-}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
NAME_TAG="${NAME_TAG:-wflike-custom-labels-infer}"
WORKERS="${WORKERS:-8}"
MIN_INTERVAL="${MIN_INTERVAL:-0.05}"
LIMIT="${LIMIT:-0}"
MIN_IU="${MIN_IU:-1}"
STOP_MODEL_ON_DONE="${STOP_MODEL_ON_DONE:-1}"
POSTER_BUCKET="${POSTER_BUCKET:-sagemaker-studio-a5572760}"
POSTER_PREFIX="${POSTER_PREFIX:-wflike-community-72k/posters}"
PROJECT_ARN="${PROJECT_ARN:-arn:aws:rekognition:us-east-1:567596065542:project/wflike-medium-clf/1785807168455}"
VERSION_ARN="${VERSION_ARN:-arn:aws:rekognition:us-east-1:567596065542:project/wflike-medium-clf/version/v202608040132/1785807179332}"
VERSION_NAME="${VERSION_NAME:-v202608040132}"
IDS_SOURCE="${IDS_SOURCE:-posters_extended}"  # posters_extended | gap | essay

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
QA="$PIPE/data/qa/medium_custom_labels"
mkdir -p "$QA"

case "$NAME_TAG" in
  wflike-vision-gap|wflike-nova-enrich*|wflike-owlv2*|wflike-imdb*)
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

USERDATA="$PIPE/aws/custom_labels_infer_userdata.sh"
CHAIN="$PIPE/aws/custom_labels_infer_chain.sh"
RUNNER="$PIPE/aws_custom_labels_infer.py"
for f in "$USERDATA" "$CHAIN" "$RUNNER"; do
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
done

echo "=== preflight: running instances (will not terminate) ==="
aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=running,pending \
  --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Name`].Value|[0],InstanceType]' \
  --output text || true

# Build ids list
IDS_FILE="$QA/infer_ids.txt"
case "$IDS_SOURCE" in
  posters_extended)
    python3 - <<'PY'
import csv
from pathlib import Path
src = Path("data/qa/vision_gap/posters_extended.csv")
out = Path("data/qa/medium_custom_labels/infer_ids.txt")
n = 0
with src.open(encoding="utf-8", errors="replace") as f, out.open("w", encoding="utf-8") as w:
    for r in csv.DictReader(f):
        w.write(f"{int(r['id'])}\n")
        n += 1
print(f"wrote {n} ids from posters_extended → {out}")
PY
    ;;
  gap)
    cp -f data/qa/vision_gap/todo_ids.txt "$IDS_FILE"
    echo "wrote $(wc -l < "$IDS_FILE") ids from vision_gap/todo_ids"
    ;;
  essay)
    # masters = have_poster − gap ≈ essay layer already scored; use gap union posters_extended
    # Prefer posters that appear in medium.csv if present; else posters_extended minus gap.
    python3 - <<'PY'
from pathlib import Path
ext = Path("data/qa/vision_gap/posters_extended.csv")
gap = {int(x.strip()) for x in Path("data/qa/vision_gap/todo_ids.txt").read_text().splitlines() if x.strip().isdigit()}
out = Path("data/qa/medium_custom_labels/infer_ids.txt")
ids = []
import csv
with ext.open(encoding="utf-8", errors="replace") as f:
    for r in csv.DictReader(f):
        i = int(r["id"])
        if i not in gap:
            ids.append(i)
out.write_text("\n".join(map(str, ids)) + "\n", encoding="utf-8")
print(f"wrote {len(ids)} essay-ish ids (extended − gap)")
PY
    ;;
  *)
    echo "unknown IDS_SOURCE=$IDS_SOURCE"; exit 1 ;;
esac
N_IDS=$(wc -l < "$IDS_FILE" | tr -d ' ')
echo "infer_ids=$N_IDS source=$IDS_SOURCE"

# Do NOT StartProjectVersion here — that bills IU while EC2 is still booting/apt.
# Chain starts the model right before DetectCustomLabels and stops on done/fail.
START_MODEL_AT_LAUNCH="${START_MODEL_AT_LAUNCH:-0}"
ST=$(aws rekognition describe-project-versions \
  --project-arn "$PROJECT_ARN" \
  --version-names "$VERSION_NAME" \
  --query 'ProjectVersionDescriptions[0].Status' --output text 2>/dev/null || echo UNKNOWN)
echo "model_status_at_launch=$ST (StartProjectVersion deferred to EC2 chain unless START_MODEL_AT_LAUNCH=1)"
if [ "$START_MODEL_AT_LAUNCH" = "1" ]; then
  if [ "$ST" != "RUNNING" ] && [ "$ST" != "STARTING" ]; then
    aws rekognition start-project-version \
      --project-version-arn "$VERSION_ARN" \
      --min-inference-units "$MIN_IU" || true
  fi
fi

echo "--- stage code + ENV + ids ---"
cat > /tmp/cl_infer_ENV <<EOF
export BUCKET=${BUCKET}
export PREFIX=${PREFIX}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
export VERSION_ARN=${VERSION_ARN}
export PROJECT_ARN=${PROJECT_ARN}
export POSTER_BUCKET=${POSTER_BUCKET}
export POSTER_PREFIX=${POSTER_PREFIX}
export WORKERS=${WORKERS}
export MIN_INTERVAL=${MIN_INTERVAL}
export LIMIT=${LIMIT}
export STOP_MODEL_ON_DONE=${STOP_MODEL_ON_DONE}
export MIN_IU=${MIN_IU}
EOF
aws s3 cp /tmp/cl_infer_ENV "s3://${BUCKET}/${PREFIX}/ENV"
aws s3 cp "$IDS_FILE" "s3://${BUCKET}/${PREFIX}/infer_ids.txt"
aws s3 cp "$CHAIN" "s3://${BUCKET}/${PREFIX}/code/aws/custom_labels_infer_chain.sh"
aws s3 cp "$USERDATA" "s3://${BUCKET}/${PREFIX}/code/aws/custom_labels_infer_userdata.sh"
aws s3 cp "$RUNNER" "s3://${BUCKET}/${PREFIX}/code/aws_custom_labels_infer.py"

TMP_UD="$(mktemp /tmp/cl_infer_ud.XXXXXX.sh)"
sed \
  -e "s|^export BUCKET=.*|export BUCKET=${BUCKET}|" \
  -e "s|^export PREFIX=.*|export PREFIX=${PREFIX}|" \
  -e "s|^export AWS_DEFAULT_REGION=.*|export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}|" \
  -e "s|^export VERSION_ARN=.*|export VERSION_ARN=${VERSION_ARN}|" \
  -e "s|^export PROJECT_ARN=.*|export PROJECT_ARN=${PROJECT_ARN}|" \
  -e "s|^export POSTER_BUCKET=.*|export POSTER_BUCKET=${POSTER_BUCKET}|" \
  -e "s|^export POSTER_PREFIX=.*|export POSTER_PREFIX=${POSTER_PREFIX}|" \
  -e "s|^export WORKERS=.*|export WORKERS=${WORKERS}|" \
  -e "s|^export MIN_INTERVAL=.*|export MIN_INTERVAL=${MIN_INTERVAL}|" \
  -e "s|^export LIMIT=.*|export LIMIT=${LIMIT}|" \
  -e "s|^export STOP_MODEL_ON_DONE=.*|export STOP_MODEL_ON_DONE=${STOP_MODEL_ON_DONE}|" \
  -e "s|^export MIN_IU=.*|export MIN_IU=${MIN_IU}|" \
  "$USERDATA" > "$TMP_UD"

echo "=== launch custom_labels_infer ==="
echo "bucket=s3://$BUCKET/$PREFIX/ type=$INSTANCE_TYPE ami=$AMI_ID"
echo "sg=$SG_ID subnet=$SUBNET_ID profile=$IAM_PROFILE Name=$NAME_TAG"
echo "N_IDS=$N_IDS WORKERS=$WORKERS MIN_INTERVAL=$MIN_INTERVAL LIMIT=$LIMIT MIN_IU=$MIN_IU"
echo "NOTE: Custom Labels ~\$4/hr/IU while RUNNING + per-image DetectCustomLabels"

ARGS=(
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --user-data "file://${TMP_UD}"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=what-fear-looks-like},{Key=Job,Value=custom-labels-infer}]"
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
echo "$IID" | tee "$QA/infer_ec2.iid"
echo "instance=$IID"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "${IP:-none}" | tee "$QA/infer_ec2.ip"

cat > "$QA/infer_launch.json" <<EOF
{
  "launched_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "instance_id": "$IID",
  "public_ip": "${IP:-none}",
  "name": "$NAME_TAG",
  "n_ids": $N_IDS,
  "ids_source": "$IDS_SOURCE",
  "version_arn": "$VERSION_ARN",
  "min_inference_units": $MIN_IU,
  "workers": $WORKERS,
  "min_interval": $MIN_INTERVAL,
  "limit": $LIMIT,
  "poster_s3": "s3://${POSTER_BUCKET}/${POSTER_PREFIX}/",
  "results_s3": "s3://${BUCKET}/${PREFIX}/results/",
  "local_csv": "data/qa/medium_custom_labels/infer_full.csv",
  "protect_left_running": ["i-07b62870cc441c343", "i-0ed17614a9172bf6c"],
  "monitor": {
    "progress": "aws s3 cp s3://${BUCKET}/${PREFIX}/results/progress.json -",
    "log": "aws s3 cp s3://${BUCKET}/${PREFIX}/results/infer_ec2.log -",
    "model": "aws rekognition describe-project-versions --project-arn $PROJECT_ARN --version-names $VERSION_NAME --query 'ProjectVersionDescriptions[0].Status' --output text"
  },
  "cost_note": "Custom Labels inference units ~\$4/hr/IU while RUNNING; stop on DONE. DetectCustomLabels per image extra. ETA ~ few hours at ~5-15 img/s depending on IU+workers."
}
EOF
aws s3 cp "$QA/infer_launch.json" "s3://${BUCKET}/${PREFIX}/results/launch.json" || true

echo "LISTO — IID=$IID IP=${IP:-none} Name=$NAME_TAG n_ids=$N_IDS"
echo "Monitor progress: aws s3 cp s3://${BUCKET}/${PREFIX}/results/progress.json -"
echo "Monitor log:      aws s3 cp s3://${BUCKET}/${PREFIX}/results/infer_ec2.log -"
echo "Model status:     aws rekognition describe-project-versions --project-arn $PROJECT_ARN --version-names $VERSION_NAME --query 'ProjectVersionDescriptions[0].Status' --output text"
echo "(instance self-terminates when chain finishes; model stopped if STOP_MODEL_ON_DONE=1)"
