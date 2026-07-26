#!/bin/bash
set -euo pipefail
export PATH=/opt/pytorch/bin:$PATH
export BUCKET=aof-owlv2-102516364259
cd ~/aof
mkdir -p pipeline/data/posters site/data pipeline/aws
tar -xf _owl_stage.tar
mv -f owlv2_creature_boxes.py pipeline/ || true
mv -f owlv2_ec2_bootstrap.sh pipeline/aws/ || true
mv -f pipeline_data/* pipeline/data/ || true
if [ -d posters ]; then
  mv posters/*.jpg pipeline/data/posters/ || true
  rmdir posters || true
fi
aws s3 cp "s3://${BUCKET}/creature_boxes.json" pipeline/data/creature_boxes.json || true
python -m pip -q install -U "transformers>=4.45" pillow pandas accelerate
nohup bash /home/ubuntu/aof/s3_watch.sh >/home/ubuntu/aof/pipeline/data/owlv2_watcher.log 2>&1 &
cd pipeline
nohup bash /home/ubuntu/aof/owl_job.sh >/home/ubuntu/aof/pipeline/data/owlv2_nohup.out 2>&1 &
echo started
sleep 8
tail -30 data/owlv2_full_run.log 2>/dev/null || tail -30 ../pipeline/data/owlv2_nohup.out || true
