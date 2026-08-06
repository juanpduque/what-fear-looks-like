#!/bin/bash
# Resumable medium-backbone embedding + compare. Safe for ~8GB RAM.
set -euo pipefail
ROOT="/Users/juanpabloduque/Documents/what-fear-looks-like"
cd "$ROOT/pipeline"
export MEDIUM_DEVICE=cpu
OUT="$ROOT/pipeline/data/qa/medium_backbone_compare"
LOG="$OUT/pipeline_embed.log"
mkdir -p "$OUT" "$ROOT/pipeline/data/qa/medium_siglip"

{
  echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) start embed pipeline ===="
  # 1) OpenCLIP ViT-L (local openai weights)
  python3 -u embed_medium_backbone.py --backbone vitl --save-every 10
  # 2) SigLIP: try SO400M, fall back to base on failure
  if ! python3 -u embed_medium_backbone.py --backbone siglip-so400m --save-every 10; then
    echo "siglip-so400m failed; trying siglip-base"
    python3 -u embed_medium_backbone.py --backbone siglip-base --save-every 10
  fi
  # 3) DINOv2 always (plan B / also useful compare)
  python3 -u embed_medium_backbone.py --backbone dinov2-base --save-every 10
  # Large only if base exists and we still want more
  python3 -u embed_medium_backbone.py --backbone dinov2-large --save-every 10 || true
  # 4) Train/eval compare from caches
  python3 -u train_medium_backbone_compare.py --from-cache --batch-size 1
  echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) done ===="
} >>"$LOG" 2>&1
