#!/usr/bin/env bash
# Launch parallel Rekognition Labels+ImageProperties+Moderation+Faces for missing JPGs.
set -euo pipefail
cd "$(dirname "$0")/.."
export AWS_PROFILE=sandbox
export AWS_DEFAULT_REGION=us-east-1
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy \
  no_proxy NO_PROXY || true

LOG=data/qa/rekognition_community_enrich.log
PIDF=data/qa/rekognition_community_enrich.pid
mkdir -p data/qa

# kill previous run if any (this job only)
if [[ -f "$PIDF" ]]; then
  old=$(cat "$PIDF" || true)
  if [[ -n "${old:-}" ]] && kill -0 "$old" 2>/dev/null; then
    echo "already running pid=$old"
    exit 0
  fi
fi

nohup python3 -u rekognition_enrich.py \
  --ids-file data/qa/rekognition_missing_ids.txt \
  --workers 10 \
  --min-interval 0.04 \
  --save-every 25 \
  --sidecar data/qa/rekognition_community_enrich.csv \
  --merge-main \
  > "$LOG" 2>&1 &
echo $! > "$PIDF"
echo "started pid=$(cat "$PIDF") log=$LOG"
sleep 3
head -20 "$LOG" || true
