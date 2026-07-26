#!/bin/bash
set -euo pipefail
export PATH=/opt/pytorch/bin:$PATH
cd /home/ubuntu/aof/pipeline
python -u owlv2_creature_boxes.py --all --device cuda --min-score 0.2 2>&1 | tee data/owlv2_full_run.log
python owlv2_creature_boxes.py --export-only
date -u +"DONE_%Y%m%dT%H%M%SZ" > data/owlv2_DONE
