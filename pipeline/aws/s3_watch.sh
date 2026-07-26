#!/bin/bash
set -euo pipefail
BUCKET=aof-owlv2-102516364259
DONE=/home/ubuntu/aof/pipeline/data/owlv2_DONE
JSON=/home/ubuntu/aof/pipeline/data/creature_boxes.json
JS=/home/ubuntu/aof/site/data/creature_boxes.js
LOG=/home/ubuntu/aof/pipeline/data/owlv2_full_run.log
WLOG=/home/ubuntu/aof/pipeline/data/owlv2_watcher.log

while [ ! -f "$DONE" ]; do
  sleep 120
  if [ -f "$JSON" ]; then
    aws s3 cp "$JSON" "s3://${BUCKET}/creature_boxes.json" --quiet || true
    [ -f "$JS" ] && aws s3 cp "$JS" "s3://${BUCKET}/creature_boxes.js" --quiet || true
    [ -f "$LOG" ] && aws s3 cp "$LOG" "s3://${BUCKET}/owlv2_full_run.log" --quiet || true
    echo "checkpoint $(date -u)" >> "$WLOG"
  fi
done

aws s3 cp "$JSON" "s3://${BUCKET}/creature_boxes.json"
aws s3 cp "$JS" "s3://${BUCKET}/creature_boxes.js"
aws s3 cp "$LOG" "s3://${BUCKET}/owlv2_full_run.log"
echo "uploaded owl $(date -u)" > /home/ubuntu/aof/pipeline/data/owlv2_UPLOADED

# Hand off to metrics (same GPU instance) instead of shutting down immediately.
bash /home/ubuntu/aof/pipeline/aws/metrics_chain.sh
