#!/bin/bash
# Multi-poster pipeline on EC2: discover → download → embed → select → S3 → halt.
set -euo pipefail
export BUCKET="${BUCKET:-aof-owlv2-102516364259}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
LOG=$PIPE/data/multi_poster_aws.log
mkdir -p "$PIPE/data/posters_multi"
exec > >(tee -a "$LOG") 2>&1

echo "=== multi_poster_chain start $(date -u) ==="
cd "$PIPE"

# TMDB key must be in /home/ubuntu/aof/.tmdb_key (mode 600), written by bootstrap
if [ -f "$ROOT/.tmdb_key" ]; then
  export TMDB_API_KEY="$(cat "$ROOT/.tmdb_key")"
fi
if [ -z "${TMDB_API_KEY:-}" ]; then
  echo "FATAL: TMDB_API_KEY missing"; exit 1
fi

python3 -m pip -q install -U pip
python3 -m pip -q install -U requests pandas numpy pillow
python3 -m pip -q install -U torch --index-url https://download.pytorch.org/whl/cpu
python3 -m pip -q install -U open_clip_torch

# Resume catalog from S3 if present
aws s3 cp "s3://${BUCKET}/metrics/multi_poster_catalog.csv" data/multi_poster_catalog.csv 2>/dev/null || true
aws s3 cp "s3://${BUCKET}/metrics/multi_poster_embeddings.npz" data/multi_poster_embeddings.npz 2>/dev/null || true
aws s3 cp "s3://${BUCKET}/metrics/multi_poster_embeddings_partial.npz" data/multi_poster_embeddings_partial.npz 2>/dev/null || true

sync_out() {
  for f in multi_poster_catalog.csv multi_poster_canonical.csv multi_poster_clusters.csv \
           multi_poster_embeddings.npz multi_poster_embeddings_partial.npz multi_poster_aws.log; do
    [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/metrics/$f" --quiet || true
  done
}

(
  while true; do
    sleep 180
    sync_out
    echo "[checkpoint $(date -u +%H:%M:%S)] synced multi-poster artifacts" || true
  done
) &
CKPID=$!

echo "--- discover ---"
python3 -u multi_poster_pipeline.py discover --langs en,null --max-list 20 --sleep 0.03
sync_out

echo "--- download ---"
python3 -u multi_poster_pipeline.py download --max-per-id 5 --workers 24
sync_out

echo "--- embed ---"
python3 -u multi_poster_pipeline.py embed --max-per-id 5
sync_out

echo "--- select ---"
python3 -u multi_poster_pipeline.py select --sim 0.96 --max-per-id 5
python3 -u multi_poster_pipeline.py report
sync_out

kill "$CKPID" 2>/dev/null || true

date -u +"MULTI_POSTER_DONE_%Y%m%dT%H%M%SZ" > data/MULTI_POSTER_DONE
aws s3 cp data/MULTI_POSTER_DONE "s3://${BUCKET}/metrics/MULTI_POSTER_DONE"
aws s3 cp data/multi_poster_aws.log "s3://${BUCKET}/metrics/multi_poster_aws.log"
echo "=== multi_poster_chain done $(date -u) ==="
sleep 20
sudo shutdown -h now
