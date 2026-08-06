#!/bin/bash
# Stage + launch EC2 for multi-poster gap (~29k films not yet in catalog).
# Extends multi_poster_* artifacts; does NOT rebuild single-poster clip_embeddings.npz.
# Does NOT download posters_multi / huge results to Mac. Does NOT terminate other jobs.
#
# Usage:
#   export AWS_PROFILE=sandbox
#   # TMDB_API_KEY from shell or S3 community copy
#   bash pipeline/aws/launch_multi_poster_gap.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy \
  no_proxy NO_PROXY || true

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-multi-poster-gap}"
INSTANCE_TYPE="${INSTANCE_TYPE:-c5.4xlarge}"
AMI_ID="${AMI_ID:-ami-052355af2a014bd2c}"  # Ubuntu 24.04 us-east-1
SG_ID="${SG_ID:-}"
SUBNET_ID="${SUBNET_ID:-}"
VPC_ID="${VPC_ID:-vpc-03b03e15ad07d5a31}"
IAM_PROFILE="${IAM_PROFILE:-wflike-ec2-train}"
KEY_NAME="${KEY_NAME:-}"
ASSOCIATE_PUBLIC_IP="${ASSOCIATE_PUBLIC_IP:-true}"
NAME_TAG="${NAME_TAG:-wflike-multi-poster-gap}"
VOLUME_GB="${VOLUME_GB:-150}"
POSTER_SRC="${POSTER_SRC:-s3://sagemaker-studio-a5572760/wflike-community-72k/posters}"
VISION_GAP_POSTERS="${VISION_GAP_POSTERS:-s3://sagemaker-studio-a5572760/wflike-vision-gap/input/posters}"
PROTECT_NAMES="${PROTECT_NAMES:-wflike-imdb-posters wflike-imdb-selenium wflike-owlv2-backfill wflike-community-72k wflike-nova-enrich wflike-vision-gap wflike-attrs-gap}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
QA=data/qa/multi_poster_gap
mkdir -p "$QA"

case "$NAME_TAG" in
  wflike-imdb-posters|wflike-imdb-selenium|wflike-owlv2-backfill|wflike-attrs-gap|wflike-vision-gap)
    echo "ERROR: refusing protected Name=$NAME_TAG"; exit 1 ;;
esac

# Refuse to touch protected running instance
if aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=running,pending \
            Name=tag:Name,Values=wflike-attrs-gap \
  --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null | grep -q .; then
  echo "INFO: wflike-attrs-gap still running — will not terminate it"
fi

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

USERDATA="$PIPE/aws/multi_poster_gap_userdata.sh"
CHAIN="$PIPE/aws/multi_poster_gap_chain.sh"
for f in "$USERDATA" "$CHAIN" multi_poster_pipeline.py clip_embed.py \
         score_multi_poster_variants_ocr.py ocr_metrics.py poster_ocr_rek_text.py; do
  [ -f "$f" ] || { echo "missing $f"; exit 1; }
done

[ -f "$QA/todo_ids.txt" ] || { echo "FATAL: missing $QA/todo_ids.txt — compute gap first"; exit 1; }
N_TODO=$(grep -c '^[0-9]' "$QA/todo_ids.txt" || echo 0)

POSTERS_CSV=""
for candidate in \
  data/qa/vision_gap/posters_extended.csv \
  data/qa/vision_gap/pull/results/posters.csv \
  data/posters.csv
do
  if [ -f "$candidate" ]; then
    POSTERS_CSV="$candidate"
    break
  fi
done
[ -n "$POSTERS_CSV" ] || { echo "FATAL: no posters.csv / posters_extended"; exit 1; }

for seed in multi_poster_catalog.csv multi_poster_canonical.csv multi_poster_clusters.csv; do
  [ -f "data/$seed" ] || { echo "FATAL: missing data/$seed"; exit 1; }
done
[ -f data/multi_poster_embeddings.npz ] || { echo "FATAL: missing data/multi_poster_embeddings.npz"; exit 1; }

# TMDB: prefer env, else S3→S3 from community_72k
TMDB_STATUS="missing"
if [ -n "${TMDB_API_KEY:-}" ]; then
  TMDB_STATUS="from_env"
elif aws s3 ls "s3://${BUCKET}/wflike-community-72k/input/qa/tmdb_api_key" >/dev/null 2>&1; then
  TMDB_STATUS="from_s3_community"
else
  # try load from zshrc without polluting
  if [ -f "$HOME/.zshrc" ]; then
    # shellcheck disable=SC1091
    set +u
    source "$HOME/.zshrc" 2>/dev/null || true
    set -u
  fi
  if [ -n "${TMDB_API_KEY:-}" ]; then
    TMDB_STATUS="from_zshrc"
  fi
fi
if [ "$TMDB_STATUS" = "missing" ]; then
  echo "FATAL: TMDB_API_KEY unavailable (env/zshrc/S3 community). STOP."
  exit 1
fi
echo "TMDB_API_KEY status=$TMDB_STATUS"

echo "=== stage multi_poster_gap → s3://$BUCKET/$PREFIX/ ==="
echo "posters_csv=$POSTERS_CSV n_todo=$N_TODO"

# Clear stale FAIL/DONE
aws s3 rm "s3://${BUCKET}/${PREFIX}/results/FAIL" 2>/dev/null || true
aws s3 rm "s3://${BUCKET}/${PREFIX}/results/DONE" 2>/dev/null || true

# Code
aws s3 cp multi_poster_pipeline.py "s3://${BUCKET}/${PREFIX}/code/multi_poster_pipeline.py"
aws s3 cp clip_embed.py "s3://${BUCKET}/${PREFIX}/code/clip_embed.py"
aws s3 cp score_multi_poster_variants_ocr.py "s3://${BUCKET}/${PREFIX}/code/score_multi_poster_variants_ocr.py"
aws s3 cp ocr_metrics.py "s3://${BUCKET}/${PREFIX}/code/ocr_metrics.py"
aws s3 cp poster_ocr_rek_text.py "s3://${BUCKET}/${PREFIX}/code/poster_ocr_rek_text.py"
aws s3 cp apply_multi_poster_ocr_swaps.py "s3://${BUCKET}/${PREFIX}/code/apply_multi_poster_ocr_swaps.py" 2>/dev/null || true
aws s3 cp "$CHAIN" "s3://${BUCKET}/${PREFIX}/code/aws/multi_poster_gap_chain.sh"
aws s3 cp "$USERDATA" "s3://${BUCKET}/${PREFIX}/code/aws/multi_poster_gap_userdata.sh"

# Input seeds (small CSVs + embeddings npz — NOT posters_multi)
aws s3 cp "$POSTERS_CSV" "s3://${BUCKET}/${PREFIX}/input/data/posters.csv"
aws s3 cp data/multi_poster_catalog.csv "s3://${BUCKET}/${PREFIX}/input/data/multi_poster_catalog.csv"
aws s3 cp data/multi_poster_canonical.csv "s3://${BUCKET}/${PREFIX}/input/data/multi_poster_canonical.csv"
aws s3 cp data/multi_poster_clusters.csv "s3://${BUCKET}/${PREFIX}/input/data/multi_poster_clusters.csv"
aws s3 cp data/multi_poster_embeddings.npz "s3://${BUCKET}/${PREFIX}/input/data/multi_poster_embeddings.npz"
# Prefer S3→S3 horror_movies if huge local pressure; local 18MB is OK
if [ -f data/horror_movies.csv ]; then
  aws s3 cp data/horror_movies.csv "s3://${BUCKET}/${PREFIX}/input/data/horror_movies.csv"
fi

# Gap QA seeds
aws s3 cp "$QA/todo_ids.txt" "s3://${BUCKET}/${PREFIX}/input/qa/todo_ids.txt"
aws s3 cp "$QA/todo_ids.csv" "s3://${BUCKET}/${PREFIX}/input/qa/todo_ids.csv"
aws s3 cp "$QA/gap_report.json" "s3://${BUCKET}/${PREFIX}/input/qa/gap_report.json"

# TMDB key to S3 (never print value)
if [ "$TMDB_STATUS" = "from_s3_community" ] && [ -z "${TMDB_API_KEY:-}" ]; then
  aws s3 cp "s3://${BUCKET}/wflike-community-72k/input/qa/tmdb_api_key" \
    "s3://${BUCKET}/${PREFIX}/input/qa/tmdb_api_key"
else
  printf '%s' "$TMDB_API_KEY" > /tmp/mpg_tmdb_key
  aws s3 cp /tmp/mpg_tmdb_key "s3://${BUCKET}/${PREFIX}/input/qa/tmdb_api_key"
  rm -f /tmp/mpg_tmdb_key
fi

# If prior results exist, leave them for chain resume (do not wipe embeddings)
if aws s3 ls "s3://${BUCKET}/${PREFIX}/results/multi_poster_catalog.csv" >/dev/null 2>&1; then
  echo "INFO: prior results/ present — chain will prefer results/ over input/ for resume"
fi

echo "=== preflight: running instances (will not terminate) ==="
aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=running,pending \
  --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Name`].Value|[0],InstanceType]' \
  --output text || true

cat > /tmp/mpg_ENV <<ENVEOF
export BUCKET=${BUCKET}
export PREFIX=${PREFIX}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
export POSTER_SRC=${POSTER_SRC}
export VISION_GAP_POSTERS=${VISION_GAP_POSTERS}
export SYNC_SECS=${SYNC_SECS:-180}
export DL_WORKERS=${DL_WORKERS:-24}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-16}
export MKL_NUM_THREADS=${MKL_NUM_THREADS:-16}
export TORCH_NUM_THREADS=${TORCH_NUM_THREADS:-16}
export OCR_WORKERS=${OCR_WORKERS:-8}
ENVEOF
aws s3 cp /tmp/mpg_ENV "s3://${BUCKET}/${PREFIX}/ENV"

TMP_UD="$(mktemp /tmp/mpg_ud.XXXXXX.sh)"
sed \
  -e "s|^export BUCKET=.*|export BUCKET=${BUCKET}|" \
  -e "s|^export PREFIX=.*|export PREFIX=${PREFIX}|" \
  -e "s|^export AWS_DEFAULT_REGION=.*|export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}|" \
  -e "s|^export POSTER_SRC=.*|export POSTER_SRC=${POSTER_SRC}|" \
  -e "s|^export VISION_GAP_POSTERS=.*|export VISION_GAP_POSTERS=${VISION_GAP_POSTERS}|" \
  "$USERDATA" > "$TMP_UD"

echo "=== launch multi_poster_gap ==="
echo "bucket=s3://$BUCKET/$PREFIX/ type=$INSTANCE_TYPE ami=$AMI_ID vol=${VOLUME_GB}G"
echo "sg=$SG_ID subnet=$SUBNET_ID profile=$IAM_PROFILE Name=$NAME_TAG todo=$N_TODO"

ARGS=(
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --user-data "file://${TMP_UD}"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=Project,Value=what-fear-looks-like},{Key=Job,Value=multi-poster-gap}]"
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
    "volume_gb": int("$VOLUME_GB"),
    "n_todo": int("$N_TODO"),
    "tmdb_key_status": "$TMDB_STATUS",
    "posters_csv_staged": "$POSTERS_CSV",
    "poster_src": "$POSTER_SRC",
    "vision_gap_posters": "$VISION_GAP_POSTERS",
    "gap": gap,
    "phases": [
        "discover", "download", "embed(merge)", "select", "report",
        "ocr_score(ge2 gap)", "apply_swaps=DEFERRED",
    ],
    "reused": [
        "multi_poster_pipeline.py",
        "score_multi_poster_variants_ocr.py",
        "local multi_poster_{catalog,canonical,clusters,embeddings}",
        "AMI/VPC/IAM from launch_attrs_gap / launch_vision_gap",
        "TMDB key pattern from community_72k",
        "does NOT touch clip_embeddings.npz single-poster corpus",
    ],
    "new": [
        "launch_multi_poster_gap.sh",
        "multi_poster_gap_chain.sh",
        "multi_poster_gap_userdata.sh",
        "data/qa/multi_poster_gap/*",
        "discover --ids-file",
    ],
    "eta_note": (
        "c5.4xlarge CPU ~29k gap: discover ~1.5-3h, download ~1-2h, "
        "CLIP embed merge ~2-5h, select ~min, OCR ge2 subset ~0.5-2h. "
        "Total rough ETA 6-12h. Volume 150GB for posters_multi."
    ),
    "monitor": {
        "progress": f"AWS_PROFILE=sandbox aws s3 cp s3://$BUCKET/$PREFIX/results/PROGRESS.json -",
        "log": f"AWS_PROFILE=sandbox aws s3 cp s3://$BUCKET/$PREFIX/results/multi_poster_gap_aws.log -",
        "ls": f"AWS_PROFILE=sandbox aws s3 ls s3://$BUCKET/$PREFIX/results/",
        "done": f"AWS_PROFILE=sandbox aws s3 cp s3://$BUCKET/$PREFIX/results/DONE -",
        "ssh": f"ssh -o StrictHostKeyChecking=no ubuntu@${IP:-none}  # if key configured",
    },
    "protect_names": "$PROTECT_NAMES".split(),
    "protect_instance": "i-0df34af493e304af7",
}
(qa / "launch.json").write_text(json.dumps(doc, indent=2) + "\n")
print(json.dumps(doc, indent=2))
PY

echo "LISTO — IID=$IID IP=${IP:-none} Name=$NAME_TAG todo=$N_TODO PREFIX=$PREFIX"
echo "Monitor:  AWS_PROFILE=sandbox aws s3 cp s3://${BUCKET}/${PREFIX}/results/PROGRESS.json -"
echo "Log:      AWS_PROFILE=sandbox aws s3 cp s3://${BUCKET}/${PREFIX}/results/multi_poster_gap_aws.log -"
