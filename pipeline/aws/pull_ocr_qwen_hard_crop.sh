#!/bin/bash
# Pull hard-crop Qwen OCR results from S3; compare vs hard + v2; terminate leftover EC2.
#
#   bash aws/pull_ocr_qwen_hard_crop.sh          # wait for DONE then pull
#   bash aws/pull_ocr_qwen_hard_crop.sh --now    # pull whatever is there
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_qwen_hard_crop}"
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

if [ -f "data/qa/${PREFIX}/det_meta.json" ]; then
  echo "--- det_meta ---"
  cat "data/qa/${PREFIX}/det_meta.json"
fi
if [ -f "data/qa/${PREFIX}/bboxes.csv" ]; then
  python3 - <<'PY'
import csv
from pathlib import Path
rows = list(csv.DictReader(Path("data/qa/ocr_qwen_hard_crop/bboxes.csv").open(encoding="utf-8")))
real = sum(1 for r in rows if not str(r.get("strategy","")).startswith("full_fallback"))
print(f"bboxes n={len(rows)} real_crops≈{real} full_fallback={len(rows)-real}")
from collections import Counter
print("strategies:", dict(Counter(r.get("strategy") for r in rows)))
print("backend:", rows[0].get("backend") if rows else None)
PY
fi

if [ -f "data/qa/${PREFIX}/results.csv" ]; then
  python3 - <<'PY'
import pandas as pd
from pathlib import Path

prefix = "ocr_qwen_hard_crop"
df = pd.read_csv(Path(f"data/qa/{prefix}/results.csv"))
print(f"\nresults rows={len(df)} models={sorted(df.model.unique())}")
print(df.groupby("model").agg(
    n=("id", "count"),
    ok=("status", lambda s: (s == "ok").sum()),
    mean_overlap=("title_overlap_score", "mean"),
    median_overlap=("title_overlap_score", "median"),
    mean_lat=("latency_s", "mean"),
).round(4).to_string())

tags = set(df.model.unique())
a, b = "qwen2b-crop", "qwen7b-crop"
if a in tags and b in tags:
    left = df[df.model == a][["id", "title_overlap_score"]].rename(columns={"title_overlap_score": "s2b"})
    right = df[df.model == b][["id", "title_overlap_score"]].rename(columns={"title_overlap_score": "s7b"})
    m = left.merge(right, on="id")
    print(f"\n2B-crop vs 7B-crop (n={len(m)}): 7B_win={(m.s7b>m.s2b).sum()} 2B_win={(m.s2b>m.s7b).sum()} tie={(m.s2b==m.s7b).sum()}")
    print(f"mean 2B={m.s2b.mean():.4f} 7B={m.s7b.mean():.4f}")

# vs prior hard (full poster)
hard = Path("data/qa/ocr_qwen_hard/results.csv")
if hard.exists():
    hdf = pd.read_csv(hard)
    for crop_tag, hard_tag in (("qwen2b-crop", "qwen2b-hard"), ("qwen7b-crop", "qwen7b-hard")):
        if crop_tag not in tags or hard_tag not in set(hdf.model):
            continue
        cur = df[df.model == crop_tag][["id", "title_overlap_score"]].rename(columns={"title_overlap_score": "s_crop"})
        pri = hdf[hdf.model == hard_tag][["id", "title_overlap_score"]].rename(columns={"title_overlap_score": "s_hard"})
        m = cur.merge(pri, on="id")
        if not len(m):
            continue
        w = (m.s_crop > m.s_hard).sum()
        l = (m.s_crop < m.s_hard).sum()
        t = (m.s_crop == m.s_hard).sum()
        print(
            f"\nvs hard {hard_tag} (tag={crop_tag}, n={len(m)}): "
            f"mean_crop={m.s_crop.mean():.4f} median_crop={m.s_crop.median():.4f} "
            f"mean_hard={m.s_hard.mean():.4f} median_hard={m.s_hard.median():.4f} "
            f"win/tie/loss={w}/{t}/{l}"
        )

# vs v2 qwen
v2 = Path("data/qa/ocr_pilot_v2/results.csv")
if v2.exists():
    prior = pd.read_csv(v2)
    prior = prior[prior.model == "qwen"][["id", "title_overlap_score"]].rename(
        columns={"title_overlap_score": "s_v2"}
    )
    for tag in (a, b):
        if tag not in tags:
            continue
        cur = df[df.model == tag][["id", "title_overlap_score"]].rename(
            columns={"title_overlap_score": "s_now"}
        )
        m = cur.merge(prior, on="id")
        if not len(m):
            continue
        w = (m.s_now > m.s_v2).sum()
        l = (m.s_now < m.s_v2).sum()
        t = (m.s_now == m.s_v2).sum()
        print(
            f"\nvs prior v2 qwen (tag={tag}, n={len(m)}): "
            f"mean_now={m.s_now.mean():.4f} median_now={m.s_now.median():.4f} "
            f"mean_v2={m.s_v2.mean():.4f} win/tie/loss={w}/{t}/{l}"
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
