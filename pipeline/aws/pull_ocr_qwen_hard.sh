#!/bin/bash
# Pull hard Qwen OCR A/B results from S3; optionally terminate leftover EC2.
#
#   bash aws/pull_ocr_qwen_hard.sh          # wait for DONE then pull
#   bash aws/pull_ocr_qwen_hard.sh --now    # pull whatever is there
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_qwen_hard}"
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
    sleep 60
    echo "  still waiting $(date -u +%H:%M:%S)"
  done
fi

aws s3 sync "s3://${BUCKET}/${PREFIX}/results/" "data/qa/${PREFIX}/"

if [ -f "data/qa/${PREFIX}/results.csv" ]; then
  python3 - <<'PY'
import pandas as pd
from pathlib import Path

prefix = "ocr_qwen_hard"
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

# Pairwise 2b vs 7b
tags = set(df.model.unique())
a, b = "qwen2b-hard", "qwen7b-hard"
if a in tags and b in tags:
    left = df[df.model == a][["id", "title_overlap_score"]].rename(
        columns={"title_overlap_score": "s2b"}
    )
    right = df[df.model == b][["id", "title_overlap_score"]].rename(
        columns={"title_overlap_score": "s7b"}
    )
    m = left.merge(right, on="id")
    win7 = (m.s7b > m.s2b).sum()
    win2 = (m.s2b > m.s7b).sum()
    tie = (m.s2b == m.s7b).sum()
    print(f"\n2B vs 7B (n={len(m)}): 7B_win={win7} 2B_win={win2} tie={tie}")
    print(f"mean 2B={m.s2b.mean():.4f} 7B={m.s7b.mean():.4f}")

# vs prior v2 qwen on same ids
v2 = Path("data/qa/ocr_pilot_v2/results.csv")
if v2.exists() and a in tags:
    prior = pd.read_csv(v2)
    prior = prior[prior.model == "qwen"][["id", "title_overlap_score"]].rename(
        columns={"title_overlap_score": "s_v2"}
    )
    cur = df[df.model == a][["id", "title_overlap_score"]].rename(
        columns={"title_overlap_score": "s_now"}
    )
    m = cur.merge(prior, on="id")
    if len(m):
        print(
            f"\nvs prior v2 qwen (tag={a}, n={len(m)}): "
            f"mean_now={m.s_now.mean():.4f} mean_v2={m.s_v2.mean():.4f}"
        )
if v2.exists() and b in tags:
    prior = pd.read_csv(v2)
    prior = prior[prior.model == "qwen"][["id", "title_overlap_score"]].rename(
        columns={"title_overlap_score": "s_v2"}
    )
    cur = df[df.model == b][["id", "title_overlap_score"]].rename(
        columns={"title_overlap_score": "s_now"}
    )
    m = cur.merge(prior, on="id")
    if len(m):
        w = (m.s_now > m.s_v2).sum()
        l = (m.s_now < m.s_v2).sum()
        t = (m.s_now == m.s_v2).sum()
        print(
            f"vs prior v2 qwen (tag={b}, n={len(m)}): "
            f"mean_now={m.s_now.mean():.4f} mean_v2={m.s_v2.mean():.4f} "
            f"win/tie/loss={w}/{t}/{l}"
        )
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
