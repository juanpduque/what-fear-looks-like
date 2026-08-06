#!/bin/bash
# Pull hard Kimi-VL OCR results from S3; optionally terminate leftover EC2.
#
#   bash aws/pull_ocr_kimi_hard.sh          # wait for DONE then pull
#   bash aws/pull_ocr_kimi_hard.sh --now    # pull whatever is there
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_kimi_hard}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p "data/qa/${PREFIX}"

WAIT=1
for a in "$@"; do
  [ "$a" = "--now" ] && WAIT=0
done

if [ "$WAIT" = "1" ]; then
  echo "waiting for s3://$BUCKET/${PREFIX}/results/DONE ..."
  while ! aws s3 ls "s3://$BUCKET/${PREFIX}/results/DONE" >/dev/null 2>&1; do
    if aws s3 ls "s3://$BUCKET/${PREFIX}/results/FAIL" >/dev/null 2>&1; then
      echo "FAIL marker present — pulling partial results"
      break
    fi
    sleep 60
    echo "  still waiting $(date -u +%H:%M:%S)"
  done
fi

aws s3 sync "s3://${BUCKET}/${PREFIX}/results/" "data/qa/${PREFIX}/"

if [ -f "data/qa/${PREFIX}/results.csv" ]; then
  python3 - <<'PY'
import pandas as pd
from pathlib import Path

prefix = "ocr_kimi_hard"
p = Path(f"data/qa/{prefix}/results.csv")
df = pd.read_csv(p)
print(f"results rows={len(df)} models={sorted(df.model.unique())}")
print(df.groupby("model").agg(
    n=("id", "count"),
    ok=("status", lambda s: (s == "ok").sum()),
    mean_overlap=("title_overlap_score", "mean"),
    median_overlap=("title_overlap_score", "median"),
    mean_lat=("latency_s", "mean"),
).round(4).to_string())

# vs qwen7b-hard on same ids
hard = Path("data/qa/ocr_qwen_hard/results.csv")
tag = "kimi-vl-hard"
if hard.exists() and tag in set(df.model.unique()):
    prior = pd.read_csv(hard)
    prior = prior[prior.model == "qwen7b-hard"][["id", "title_overlap_score"]].rename(
        columns={"title_overlap_score": "s7b"}
    )
    cur = df[df.model == tag][["id", "title_overlap_score"]].rename(
        columns={"title_overlap_score": "s_kimi"}
    )
    m = cur.merge(prior, on="id")
    if len(m):
        w = (m.s_kimi > m.s7b).sum()
        l = (m.s_kimi < m.s7b).sum()
        t = (m.s_kimi == m.s7b).sum()
        print(
            f"\nvs qwen7b-hard (n={len(m)}): "
            f"mean_kimi={m.s_kimi.mean():.4f} mean_7b={m.s7b.mean():.4f} "
            f"win/tie/loss={w}/{t}/{l}"
        )
        print(m.assign(delta=m.s_kimi - m.s7b).to_string(index=False))
PY
else
  echo "WARNING: results.csv not present yet"
  ls -la "data/qa/${PREFIX}/" | head -40
fi

IID_FILE="data/qa/${PREFIX}_ec2.iid"
if [ -f "$IID_FILE" ]; then
  IID=$(tr -d '[:space:]' < "$IID_FILE")
  STATE=$(aws ec2 describe-instances --instance-ids "$IID" \
    --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || echo none)
  echo "ec2 $IID state=$STATE"
  if [ "$STATE" = "running" ] || [ "$STATE" = "pending" ] || [ "$STATE" = "stopping" ]; then
    echo "terminating leftover instance $IID"
    aws ec2 terminate-instances --instance-ids "$IID" >/dev/null
  fi
fi

echo "LISTO — data/qa/${PREFIX}/"
