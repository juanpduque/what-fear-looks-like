#!/bin/bash
# Rekognition ENRICH only (DetectLabels/Moderation/Faces). No DetectText.
# Uploads via boto3 (not awscli — the Ubuntu AMI's awscli is broken).
# On-demand safe: checkpoints every 2 min, verifies first upload, halts when done.
set -euo pipefail
export BUCKET="${BUCKET:-aof-owlv2-102516364259}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
LOG=$PIPE/data/rekognition_aws.log
mkdir -p "$PIPE/data/posters"
exec > >(tee -a "$LOG") 2>&1

echo "=== rek_chain ENRICH-ONLY start $(date -u) ==="
cd "$PIPE"
python3 -m pip -q install -U boto3 pandas pillow

# boto3 uploader — avoids broken system awscli (KeyError: opsworkscm)
cat > /tmp/s3_put.py <<'PY'
import os, sys
from pathlib import Path
import boto3
bucket = os.environ["BUCKET"]
region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
s3 = boto3.client("s3", region_name=region)
ok = 0
for name in sys.argv[1:]:
    p = Path("data") / name
    if not p.exists():
        print(f"skip missing {name}")
        continue
    key = f"metrics/{name}"
    s3.upload_file(str(p), bucket, key)
    print(f"uploaded s3://{bucket}/{key} ({p.stat().st_size} bytes)")
    ok += 1
if ok == 0:
    raise SystemExit("no files uploaded")
PY

sync_out() {
  python3 /tmp/s3_put.py rekognition.csv rekognition_decade.json rekognition_aws.log
}

# Prove S3 write works BEFORE the long job.
echo "--- verify S3 write ---"
echo "S3_WRITE_OK_$(date -u +%Y%m%dT%H%M%SZ)" > data/REK_S3_PROBE
python3 /tmp/s3_put.py REK_S3_PROBE
echo "S3 write OK"

(
  while true; do
    sleep 120
    sync_out && echo "[checkpoint $(date -u +%H:%M:%S)] synced enrich csv to s3" || echo "[checkpoint FAIL $(date -u +%H:%M:%S)]"
  done
) &
CKPID=$!

echo "--- rekognition_enrich ---"
python3 -u rekognition_enrich.py --save-every 50
sync_out

kill "$CKPID" 2>/dev/null || true

date -u +"REK_ENRICH_DONE_%Y%m%dT%H%M%SZ" > data/REK_DONE
python3 /tmp/s3_put.py REK_DONE rekognition.csv rekognition_decade.json rekognition_aws.log
echo "=== rek_chain ENRICH-ONLY done $(date -u) ==="
sleep 20
sudo shutdown -h now
