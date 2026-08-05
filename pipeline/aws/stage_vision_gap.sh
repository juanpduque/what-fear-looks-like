#!/bin/bash
# Stage vision-gap inputs to S3 (masters, extended posters.csv, todo lists, must_upload JPGs).
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/stage_vision_gap.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy \
  no_proxy NO_PROXY || true

export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-vision-gap}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
QA=data/qa/vision_gap

[ -f "$QA/gap_report.json" ] || { echo "missing $QA/gap_report.json — compute gaps first"; exit 1; }
[ -f "$QA/posters_extended.csv" ] || { echo "missing posters_extended.csv"; exit 1; }
[ -f "$QA/todo_ids.txt" ] || { echo "missing todo_ids.txt"; exit 1; }

echo "=== stage vision_gap → s3://$BUCKET/$PREFIX/ ==="

# Extended meta as posters.csv for the workers
aws s3 cp "$QA/posters_extended.csv" "s3://${BUCKET}/${PREFIX}/input/data/posters.csv"

# Seed masters
for f in faces_v2.csv census.csv attributes.csv segmentation.csv typography.csv medium.csv \
         faces_v2_decade.json census_decade.json attributes_decade.json segmentation_decade.json \
         typography_decade.json medium_yearly.json clip_embeddings.npz; do
  [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/${PREFIX}/input/data/$f" || true
done

# Gap lists / report
aws s3 cp "$QA/gap_report.json" "s3://${BUCKET}/${PREFIX}/input/data/qa/vision_gap/gap_report.json"
aws s3 cp "$QA/todo_ids.txt" "s3://${BUCKET}/${PREFIX}/input/data/qa/vision_gap/todo_ids.txt"
aws s3 cp "$QA/s3_only_todo_ids.txt" "s3://${BUCKET}/${PREFIX}/input/data/qa/vision_gap/s3_only_todo_ids.txt"
aws s3 cp "$QA/local_todo_ids.txt" "s3://${BUCKET}/${PREFIX}/input/data/qa/vision_gap/local_todo_ids.txt"
aws s3 cp "$QA/must_upload_ids.txt" "s3://${BUCKET}/${PREFIX}/input/data/qa/vision_gap/must_upload_ids.txt"

# Code
for f in faces_v2.py multi_analyze.py clip_embed.py clip_census.py clip_typography_axis.py \
         clip_medium.py segmentation.py; do
  aws s3 cp "$f" "s3://${BUCKET}/${PREFIX}/code/$f"
done
aws s3 cp aws/vision_gap_chain.sh "s3://${BUCKET}/${PREFIX}/code/aws/vision_gap_chain.sh"
aws s3 cp aws/vision_gap_userdata.sh "s3://${BUCKET}/${PREFIX}/code/aws/vision_gap_userdata.sh"

# Must-upload posters (~1.1k, ~0.3GB) not in community S3
echo "--- upload must_upload posters ---"
python3 - <<'PY'
import concurrent.futures, subprocess, os
from pathlib import Path
PIPE = Path(".").resolve()
ids = [int(x) for x in (PIPE/"data/qa/vision_gap/must_upload_ids.txt").read_text().split() if x.strip()]
bucket = os.environ.get("BUCKET", "sagemaker-studio-a5572760")
prefix = os.environ.get("PREFIX", "wflike-vision-gap")
POSTERS = PIPE / "data/posters"

def up(pid: int) -> str:
    src = POSTERS / f"{pid}.jpg"
    if not src.exists():
        return "miss"
    dst = f"s3://{bucket}/{prefix}/input/posters/{pid}.jpg"
    r = subprocess.run(["aws", "s3", "cp", str(src), dst, "--quiet"], capture_output=True)
    return "ok" if r.returncode == 0 else "err"

ok = err = miss = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
    for i, st in enumerate(ex.map(up, ids), 1):
        if st == "ok": ok += 1
        elif st == "miss": miss += 1
        else: err += 1
        if i % 100 == 0 or i == len(ids):
            print(f"  upload {i}/{len(ids)} ok={ok} err={err} miss={miss}", flush=True)
print(f"LISTO must_upload ok={ok} err={err} miss={miss}")
PY

echo "=== stage done ==="
echo "Monitor later: aws s3 ls s3://${BUCKET}/${PREFIX}/"
