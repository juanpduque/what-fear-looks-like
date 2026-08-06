#!/bin/bash
# cloud-init: Real-ESRGAN poster upscale
exec > >(tee /home/ubuntu/poster_upscale_userdata.log) 2>&1
set -euo pipefail
export BUCKET=aof-owlv2-102516364259
export PREFIX=poster_upscale
export AWS_DEFAULT_REGION=us-east-1
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH

echo "=== ${PREFIX} userdata start $(date -u) ==="
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
mkdir -p "$PIPE/aws" "$PIPE/data/qa/${PREFIX}" "$PIPE/weights"

for i in $(seq 1 30); do
  if aws sts get-caller-identity >/dev/null 2>&1; then break; fi
  sleep 2
done

aws s3 cp "s3://${BUCKET}/${PREFIX}/code/poster_upscale_chain.sh" "$PIPE/aws/poster_upscale_chain.sh"
aws s3 cp "s3://${BUCKET}/${PREFIX}/code/upscale_posters_realesrgan.py" "$PIPE/upscale_posters_realesrgan.py"
chmod +x "$PIPE/aws/poster_upscale_chain.sh"

chown -R ubuntu:ubuntu "$ROOT"
sudo -u ubuntu -H bash -lc "cd $PIPE && bash aws/poster_upscale_chain.sh"
