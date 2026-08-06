#!/bin/bash
# Stage + launch EC2 for attributes-only gap (opencv-contrib / saliency fix).
# Does NOT upload posters or clip_embeddings. Does NOT terminate other jobs.
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/launch_attrs_gap.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy \
  no_proxy NO_PROXY || true

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-attrs-gap}"
INSTANCE_TYPE="${INSTANCE_TYPE:-c5.4xlarge}"
AMI_ID="${AMI_ID:-ami-052355af2a014bd2c}"  # Ubuntu 24.04 us-east-1
SG_ID="${SG_ID:-}"
SUBNET_ID="${SUBNET_ID:-}"
VPC_ID="${VPC_ID:-vpc-03b03e15ad07d5a31}"
IAM_PROFILE="${IAM_PROFILE:-wflike-ec2-train}"
KEY_NAME="${KEY_NAME:-}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
NAME_TAG="${NAME_TAG:-wflike-attrs-gap}"
VOLUME_GB="${VOLUME_GB:-100}"
POSTER_SRC="${POSTER_SRC:-s3://sagemaker-studio-a5572760/wflike-community-72k/posters}"
VISION_GAP_POSTERS="${VISION_GAP_POSTERS:-s3://sagemaker-studio-a5572760/wflike-vision-gap/input/posters}"
PROTECT_NAMES="${PROTECT_NAMES:-wflike-imdb-posters wflike-imdb-selenium wflike-owlv2-backfill wflike-community-72k wflike-nova-enrich wflike-vision-gap}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
QA=data/qa/attrs_gap
mkdir -p "$QA"

case "$NAME_TAG" in
  wflike-imdb-posters|wflike-imdb-selenium|wflike-owlv2-backfill|wflike-vision-gap)
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

USERDATA="$PIPE/aws/attrs_gap_userdata.sh"
CHAIN="$PIPE/aws/attrs_gap_chain.sh"
for f in "$USERDATA" "$CHAIN" multi_analyze.py; do
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
done

# Resolve posters.csv (prefer extended / vision-gap pull — do NOT sync JPGs)
POSTERS_CSV=""
for candidate in \
  data/qa/vision_gap/pull/results/posters.csv \
  data/qa/vision_gap/posters_extended.csv \
  data/posters.csv
do
  if [ -f "$candidate" ]; then
    POSTERS_CSV="$candidate"
    break
  fi
done
[ -n "$POSTERS_CSV" ] || { echo "FATAL: no posters.csv found"; exit 1; }

ATTRS_CSV=data/attributes.csv
[ -f "$ATTRS_CSV" ] || ATTRS_CSV=data/qa/vision_gap/pull/results/attributes.csv
[ -f "$ATTRS_CSV" ] || { echo "FATAL: no attributes.csv"; exit 1; }

FACES_CSV=""
for candidate in data/faces_v2.csv data/qa/vision_gap/pull/results/faces_v2.csv; do
  [ -f "$candidate" ] && FACES_CSV="$candidate" && break
done

echo "=== stage attrs_gap → s3://$BUCKET/$PREFIX/ ==="
echo "posters_csv=$POSTERS_CSV attrs=$ATTRS_CSV faces=${FACES_CSV:-none}"

aws s3 cp "$POSTERS_CSV" "s3://${BUCKET}/${PREFIX}/input/data/posters.csv"

# Prefer latest cloud attributes seed (S3→S3, no Mac download) if present
if aws s3 ls "s3://${BUCKET}/${PREFIX}/results/attributes.csv" >/dev/null 2>&1; then
  echo "seed attributes from previous results/ (S3→S3)"
  aws s3 cp "s3://${BUCKET}/${PREFIX}/results/attributes.csv" \
    "s3://${BUCKET}/${PREFIX}/input/data/attributes.csv"
  aws s3 cp "s3://${BUCKET}/${PREFIX}/results/attributes_partial.csv" \
    "s3://${BUCKET}/${PREFIX}/input/data/attributes_partial.csv" 2>/dev/null \
    || aws s3 cp "s3://${BUCKET}/${PREFIX}/results/attributes.csv" \
         "s3://${BUCKET}/${PREFIX}/input/data/attributes_partial.csv"
else
  aws s3 cp "$ATTRS_CSV" "s3://${BUCKET}/${PREFIX}/input/data/attributes.csv"
  if [ -f data/attributes_partial.csv ]; then
    aws s3 cp data/attributes_partial.csv "s3://${BUCKET}/${PREFIX}/input/data/attributes_partial.csv"
  else
    aws s3 cp "$ATTRS_CSV" "s3://${BUCKET}/${PREFIX}/input/data/attributes_partial.csv"
  fi
fi
[ -f data/attributes_decade.json ] && \
  aws s3 cp data/attributes_decade.json "s3://${BUCKET}/${PREFIX}/input/data/attributes_decade.json" || true
[ -n "$FACES_CSV" ] && aws s3 cp "$FACES_CSV" "s3://${BUCKET}/${PREFIX}/input/data/faces_v2.csv" || true

aws s3 cp multi_analyze.py "s3://${BUCKET}/${PREFIX}/code/multi_analyze.py"
aws s3 cp "$CHAIN" "s3://${BUCKET}/${PREFIX}/code/aws/attrs_gap_chain.sh"
aws s3 cp "$USERDATA" "s3://${BUCKET}/${PREFIX}/code/aws/attrs_gap_userdata.sh"

# Clear stale FAIL/DONE so monitors don't confuse runs
aws s3 rm "s3://${BUCKET}/${PREFIX}/results/FAIL" 2>/dev/null || true
aws s3 rm "s3://${BUCKET}/${PREFIX}/results/DONE" 2>/dev/null || true

N_TODO=$(python3 - <<PY
import pandas as pd
from pathlib import Path
# Prefer staged cloud seed count via a tiny local probe file if we just synced;
# otherwise local ATTRS_CSV. Actual gap on EC2 uses S3-seeded attributes.
attrs_path = Path(r"$ATTRS_CSV")
attrs = set(pd.read_csv(attrs_path, usecols=["id"])["id"].astype(int))
faces_s = r"$FACES_CSV"
faces_p = Path(faces_s) if faces_s else None
if faces_p and faces_p.exists() and faces_s not in ("", "."):
    faces = set(pd.read_csv(faces_p, usecols=["id"])["id"].astype(int))
    print(len(faces - attrs))
else:
    meta = set(pd.read_csv(r"$POSTERS_CSV", usecols=["id"])["id"].astype(int))
    print(len(meta - attrs))
PY
)
# Better estimate: query unique ids from staged S3 attributes (stream, no full Mac write)
N_TODO=$(aws s3 cp "s3://${BUCKET}/${PREFIX}/input/data/attributes.csv" - 2>/dev/null \
  | python3 -c "
import sys, pandas as pd
from pathlib import Path
attrs=set(pd.read_csv(sys.stdin, usecols=['id'])['id'].astype(int))
faces=None
for p in ['data/faces_v2.csv','data/qa/vision_gap/pull/results/faces_v2.csv']:
    if Path(p).exists():
        faces=set(pd.read_csv(p, usecols=['id'])['id'].astype(int)); break
print(len(faces-attrs) if faces is not None else max(0, 65201-len(attrs)))
" 2>/dev/null || echo "$N_TODO")
echo "n_todo≈$N_TODO (seed attrs from s3 input or local)"

echo "=== preflight: running instances (will not terminate) ==="
aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=running,pending \
  --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Name`].Value|[0],InstanceType]' \
  --output text || true

cat > /tmp/attrs_gap_ENV <<ENVEOF
export BUCKET=${BUCKET}
export PREFIX=${PREFIX}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
export POSTER_SRC=${POSTER_SRC}
export VISION_GAP_POSTERS=${VISION_GAP_POSTERS}
export SYNC_SECS=${SYNC_SECS:-180}
export DL_WORKERS=${DL_WORKERS:-32}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-16}
export MKL_NUM_THREADS=${MKL_NUM_THREADS:-16}
ENVEOF
aws s3 cp /tmp/attrs_gap_ENV "s3://${BUCKET}/${PREFIX}/ENV"

TMP_UD="$(mktemp /tmp/attrs_gap_ud.XXXXXX.sh)"
sed \
  -e "s|^export BUCKET=.*|export BUCKET=${BUCKET}|" \
  -e "s|^export PREFIX=.*|export PREFIX=${PREFIX}|" \
  -e "s|^export AWS_DEFAULT_REGION=.*|export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}|" \
  -e "s|^export POSTER_SRC=.*|export POSTER_SRC=${POSTER_SRC}|" \
  -e "s|^export VISION_GAP_POSTERS=.*|export VISION_GAP_POSTERS=${VISION_GAP_POSTERS}|" \
  "$USERDATA" > "$TMP_UD"

echo "=== launch attrs_gap ==="
echo "bucket=s3://$BUCKET/$PREFIX/ type=$INSTANCE_TYPE ami=$AMI_ID vol=${VOLUME_GB}G"
echo "sg=$SG_ID subnet=$SUBNET_ID profile=$IAM_PROFILE Name=$NAME_TAG todo=$N_TODO"
echo "saliency_fix=opencv-contrib-python-headless + assert hasattr(cv2,'saliency')"

ARGS=(
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --user-data "file://${TMP_UD}"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=what-fear-looks-like},{Key=Job,Value=attrs-gap}]"
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
echo "$IID" | tee "$QA/ec2.iid"
echo "instance=$IID"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "${IP:-none}" | tee "$QA/ec2.ip"

python3 <<PY
import json
from pathlib import Path
from datetime import datetime, timezone
qa = Path("$QA")
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
    "volume_gb": int("$VOLUME_GB"),
    "n_todo": int("$N_TODO"),
    "posters_csv_staged": "$POSTERS_CSV",
    "poster_src": "$POSTER_SRC",
    "vision_gap_posters": "$VISION_GAP_POSTERS",
    "pipelines": ["attributes"],
    "saliency_fix": "opencv-contrib + HoughLinesP reshape(-1,4) + defensive MSER/saliency unpack + smoke metrics",
    "eta_note": "Attrs-only ~27k on c5.4xlarge: download ~15-30m + analyze ~2-4h (rough). Hough unpack TypeError fixed.",
    "monitor": {
        "progress": f"aws s3 cp s3://$BUCKET/$PREFIX/results/PROGRESS.json -",
        "log": f"aws s3 cp s3://$BUCKET/$PREFIX/results/attrs_gap_aws.log -",
        "ls": f"aws s3 ls s3://$BUCKET/$PREFIX/results/",
        "gate": f"aws s3 cp s3://$BUCKET/$PREFIX/results/GATE.json -",
    },
    "protect_names": "$PROTECT_NAMES".split(),
}
(qa / "launch.json").write_text(json.dumps(doc, indent=2) + "\n")
print(json.dumps(doc, indent=2))
PY

echo "LISTO — IID=$IID IP=${IP:-none} Name=$NAME_TAG todo=$N_TODO"
echo "Monitor:  AWS_PROFILE=sandbox aws s3 cp s3://${BUCKET}/${PREFIX}/results/PROGRESS.json -"
echo "Log:      AWS_PROFILE=sandbox aws s3 cp s3://${BUCKET}/${PREFIX}/results/attrs_gap_aws.log -"
