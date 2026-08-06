#!/bin/bash
# cloud-init: CLIP medium classifier on g4dn → S3
exec > >(tee /home/ubuntu/medium_clf_userdata.log) 2>&1
set -euo pipefail
export AWS_DEFAULT_REGION=us-east-1
export BUCKET=sagemaker-studio-a5572760
export PREFIX=wflike-medium-clf
export PATH=/opt/pytorch/bin:/usr/local/bin:$PATH

echo "=== medium clf userdata $(date -u) ==="
for i in $(seq 1 30); do
  aws sts get-caller-identity >/dev/null 2>&1 && break
  sleep 2
done

ROOT=/home/ubuntu/wflike
mkdir -p "$ROOT/data/qa/medium_clf" "$ROOT/data"
cd "$ROOT"

aws s3 cp "s3://${BUCKET}/${PREFIX}/code/train_medium_classifier.py" ./train_medium_classifier.py
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/label_qa_medium_train.csv" ./data/label_qa_medium_train.csv
aws s3 cp "s3://${BUCKET}/${PREFIX}/input/clip_embeddings.npz" ./data/clip_embeddings.npz

PYTHON=python3
command -v /opt/pytorch/bin/python >/dev/null && PYTHON=/opt/pytorch/bin/python
$PYTHON -m pip -q install -U scikit-learn joblib numpy
$PYTHON -u train_medium_classifier.py \
  --labels data/label_qa_medium_train.csv \
  --embeddings data/clip_embeddings.npz \
  --out-dir data/qa/medium_clf \
  --pred-out data/medium_pred.csv

# stamp GPU run
hostname > data/qa/medium_clf/hostname.txt
nvidia-smi -L > data/qa/medium_clf/gpu.txt 2>/dev/null || echo "no-gpu" > data/qa/medium_clf/gpu.txt
date -u +"g4dn_done_%Y%m%dT%H%M%SZ" > data/qa/medium_clf/DONE

aws s3 sync data/qa/medium_clf "s3://${BUCKET}/${PREFIX}/output/medium_clf/" --only-show-errors
aws s3 cp data/medium_pred.csv "s3://${BUCKET}/${PREFIX}/output/medium_pred.csv" --only-show-errors
echo "=== done $(date -u) ==="
sleep 15
sudo shutdown -h now
