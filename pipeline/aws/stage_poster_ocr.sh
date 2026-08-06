#!/bin/bash
# Stage posters + OCR code to S3 for the EC2 EasyOCR job.
#
# Usage (from repo root or pipeline/):
#   bash pipeline/aws/stage_poster_ocr.sh
#   bash pipeline/aws/stage_poster_ocr.sh --dry-run
#   LIMIT=100 bash pipeline/aws/stage_poster_ocr.sh   # stage only first N ids
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

DRY=0
for a in "$@"; do
  [ "$a" = "--dry-run" ] && DRY=1
done

echo "=== stage_poster_ocr → s3://$BUCKET/poster_ocr/ ==="
echo "posters dir: data/posters"
echo "corpus: $(wc -l < data/posters.csv) rows in posters.csv"

# Build a staging list of jpgs that exist for corpus ids
STAGE_DIR=data/qa/_poster_ocr_stage
mkdir -p "$STAGE_DIR/posters" "$STAGE_DIR/code"
cp -f poster_ocr.py "$STAGE_DIR/code/poster_ocr.py"
cp -f aws/poster_ocr_chain.sh "$STAGE_DIR/code/poster_ocr_chain.sh"
cp -f data/posters.csv "$STAGE_DIR/posters.csv"

python3 - <<'PY'
import os, shutil
from pathlib import Path
import pandas as pd

limit = int(os.environ.get("LIMIT") or "0")
data = Path("data")
stage = data / "qa" / "_poster_ocr_stage" / "posters"
stage.mkdir(parents=True, exist_ok=True)
ids = pd.read_csv(data / "posters.csv", usecols=["id"])["id"].astype(int).tolist()
if limit > 0:
    ids = ids[:limit]
src = data / "posters"
ok = miss = 0
# Only copy missing into stage (hardlink when possible to save space/time)
for pid in ids:
    s = src / f"{pid}.jpg"
    d = stage / f"{pid}.jpg"
    if d.exists():
        ok += 1
        continue
    if not s.exists():
        miss += 1
        continue
    try:
        os.link(s, d)
    except OSError:
        shutil.copy2(s, d)
    ok += 1
print(f"staged jpgs={ok:,} missing_local={miss:,} limit={limit or 'all'}")
PY

if [ "$DRY" = "1" ]; then
  echo "DRY RUN — not uploading"
  ls -lh "$STAGE_DIR/code" "$STAGE_DIR/posters.csv"
  echo "jpg count staged: $(ls "$STAGE_DIR/posters"/*.jpg 2>/dev/null | wc -l)"
  exit 0
fi

echo "--- upload code + posters.csv ---"
aws s3 cp "$STAGE_DIR/code/poster_ocr.py" "s3://${BUCKET}/poster_ocr/code/poster_ocr.py"
aws s3 cp "$STAGE_DIR/code/poster_ocr_chain.sh" "s3://${BUCKET}/poster_ocr/code/poster_ocr_chain.sh"
aws s3 cp "$STAGE_DIR/posters.csv" "s3://${BUCKET}/poster_ocr/posters.csv"
aws s3 cp aws/poster_ocr_userdata.sh "s3://${BUCKET}/poster_ocr/code/poster_ocr_userdata.sh"

echo "--- sync posters (may take a while; ~2–3 GB) ---"
aws s3 sync "$STAGE_DIR/posters/" "s3://${BUCKET}/poster_ocr/posters/" --size-only

echo "LISTO — stage en s3://${BUCKET}/poster_ocr/"
echo "Siguiente: bash pipeline/aws/launch_poster_ocr.sh"
