#!/bin/bash
# Pull hard12_new OCR results from S3; optionally terminate leftover EC2.
#
#   bash aws/pull_ocr_hard12_new.sh          # wait for DONE then pull
#   bash aws/pull_ocr_hard12_new.sh --now    # pull whatever is there
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_hard12_new}"
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

prefix = "ocr_hard12_new"
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

# vs kimi-vl-hard on same ids
kimi_path = Path("data/qa/ocr_kimi_hard/results.csv")
tags = [t for t in ("glm-ocr-hard", "unlimited-ocr-hard", "deepseek-ocr2-hard") if t in set(df.model.unique())]
if kimi_path.exists() and tags:
    prior = pd.read_csv(kimi_path)
    prior = prior[prior.model == "kimi-vl-hard"][["id", "title_overlap_score"]].rename(
        columns={"title_overlap_score": "s_kimi"}
    )
    for tag in tags:
        cur = df[df.model == tag][["id", "title_overlap_score"]].rename(
            columns={"title_overlap_score": "s_cur"}
        )
        m = cur.merge(prior, on="id")
        if not len(m):
            continue
        w = (m.s_cur > m.s_kimi).sum()
        l = (m.s_cur < m.s_kimi).sum()
        t = (m.s_cur == m.s_kimi).sum()
        print(
            f"\n{tag} vs kimi-vl-hard (n={len(m)}): "
            f"mean={m.s_cur.mean():.4f} mean_kimi={m.s_kimi.mean():.4f} "
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
