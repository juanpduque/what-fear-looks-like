#!/usr/bin/env bash
# Bootstrap OWLv2 creature-box full run on a Deep Learning AMI / GPU instance.
# Expected: Ubuntu + NVIDIA driver + CUDA. Run from repo root on the instance.
#
#   bash pipeline/aws/owlv2_ec2_bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/miniforge3/bin:$HOME/mambaforge/bin:$PATH"

python3 - <<'PY'
import torch
assert torch.cuda.is_available(), "CUDA not available — wrong instance/AMI?"
print("GPU:", torch.cuda.get_device_name(0))
PY

python3 -m pip -q install -U "transformers>=4.45" pillow pandas accelerate

cd pipeline
# Resume-friendly full corpus (skip ids already in creature_boxes.json)
python3 -u owlv2_creature_boxes.py --all --device cuda --min-score 0.2 \
  2>&1 | tee data/owlv2_full_run.log

python3 owlv2_creature_boxes.py --export-only
echo "DONE — copy data/creature_boxes.json + ../site/data/creature_boxes.js back to laptop"
