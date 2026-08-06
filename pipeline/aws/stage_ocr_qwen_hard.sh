#!/bin/bash
# Stage mini-pilot: hard Qwen OCR ids (title_overlap < 1 in ocr_pilot_v2) for
# 2B vs 7B comparison.
#
# Poster priority (never invent letterbox-from-w342 as "homolog"):
#   1) true posters_homolog (local or S3)
#   2) posters_original_up
#   3) posters_original
#   4) data/posters (w342) — documented only; NOT labeled homolog
#
# Usage:
#   bash aws/stage_ocr_qwen_hard.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_qwen_hard}"
MAX_N="${MAX_N:-120}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

echo "=== stage_${PREFIX} → s3://$BUCKET/${PREFIX}/ ==="

mkdir -p "data/qa/${PREFIX}"

# Build hard sample from ocr_pilot_v2 if missing
if [ ! -f "data/qa/${PREFIX}/sample_ids.txt" ]; then
  python3 - <<'PY'
import csv
from pathlib import Path
import pandas as pd

src = Path("data/qa/ocr_pilot_v2/results.csv")
out = Path("data/qa/ocr_qwen_hard")
out.mkdir(parents=True, exist_ok=True)
hard = []
for r in csv.DictReader(src.open(encoding="utf-8")):
    if r.get("model") != "qwen":
        continue
    try:
        s = float(r.get("title_overlap_score") or "")
    except ValueError:
        continue
    if s < 1:
        hard.append((int(r["id"]), s))
hard.sort(key=lambda x: x[0])
ids = [i for i, _ in hard]
(out / "sample_ids.txt").write_text("\n".join(str(i) for i in ids) + "\n")
posters = pd.read_csv("data/posters.csv", usecols=["id", "title", "year"])
m = posters[posters["id"].astype(int).isin(ids)].copy()
score = {i: s for i, s in hard}
order = {i: k for k, i in enumerate(ids)}
m["_ord"] = m["id"].astype(int).map(order)
m = m.sort_values("_ord").drop(columns=["_ord"])
m["prior_qwen_overlap"] = m["id"].astype(int).map(score)
m.to_csv(out / "sample_meta.csv", index=False)
print(f"built hard sample n={len(ids)}", flush=True)
PY
fi

N_LOCAL=$(wc -l < "data/qa/${PREFIX}/sample_ids.txt" | tr -d ' ')
if [ "$N_LOCAL" -gt "$MAX_N" ]; then
  echo "ERROR: sample has $N_LOCAL ids — refuse >$MAX_N"; exit 1
fi
if [ "$N_LOCAL" -lt 1 ]; then
  echo "ERROR: empty sample_ids.txt"; exit 1
fi
echo "sample_n=$N_LOCAL (hard qwen title_overlap < 1)"

STAGE="data/qa/_${PREFIX}_stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/code" "$STAGE/posters" "$STAGE/qa"

cp -f pilot_ocr_models.py "$STAGE/code/pilot_ocr_models.py"
cp -f ocr_metrics.py "$STAGE/code/ocr_metrics.py"
cp -f aws/ocr_qwen_hard_chain.sh "$STAGE/code/ocr_qwen_hard_chain.sh"
cp -f aws/ocr_qwen_hard_userdata.sh "$STAGE/code/ocr_qwen_hard_userdata.sh"

export PREFIX BUCKET MAX_N
python3 aws/_stage_ocr_qwen_hard_posters.py

cp -f "data/qa/${PREFIX}/sample_ids.txt" "$STAGE/qa/sample_ids.txt"
[ -f "data/qa/${PREFIX}/sample_meta.csv" ] && \
  cp -f "data/qa/${PREFIX}/sample_meta.csv" "$STAGE/qa/sample_meta.csv"
[ -f "data/qa/${PREFIX}/poster_sources.csv" ] && \
  cp -f "data/qa/${PREFIX}/poster_sources.csv" "$STAGE/qa/poster_sources.csv"

N_LOCAL=$(wc -l < "data/qa/${PREFIX}/sample_ids.txt" | tr -d ' ')
echo "final sample_n=$N_LOCAL"
echo "jpg count: $(ls "$STAGE/posters"/*.jpg 2>/dev/null | wc -l | tr -d ' ')"

echo "--- upload code + ids + subset posters.csv ---"
aws s3 cp "$STAGE/code/pilot_ocr_models.py" "s3://${BUCKET}/${PREFIX}/code/pilot_ocr_models.py"
aws s3 cp "$STAGE/code/ocr_metrics.py" "s3://${BUCKET}/${PREFIX}/code/ocr_metrics.py"
aws s3 cp "$STAGE/code/ocr_qwen_hard_chain.sh" "s3://${BUCKET}/${PREFIX}/code/ocr_qwen_hard_chain.sh"
aws s3 cp "$STAGE/code/ocr_qwen_hard_userdata.sh" "s3://${BUCKET}/${PREFIX}/code/ocr_qwen_hard_userdata.sh"
aws s3 cp "$STAGE/qa/sample_ids.txt" "s3://${BUCKET}/${PREFIX}/sample_ids.txt"
aws s3 cp "$STAGE/posters.csv" "s3://${BUCKET}/${PREFIX}/posters.csv"
[ -f "$STAGE/qa/sample_meta.csv" ] && aws s3 cp "$STAGE/qa/sample_meta.csv" "s3://${BUCKET}/${PREFIX}/sample_meta.csv"
[ -f "$STAGE/qa/poster_sources.csv" ] && aws s3 cp "$STAGE/qa/poster_sources.csv" "s3://${BUCKET}/${PREFIX}/poster_sources.csv"

MODELS="${MODELS:-qwen,qwen7}"
printf '%s\n' "$MODELS" | aws s3 cp - "s3://${BUCKET}/${PREFIX}/MODELS"
echo "staged MODELS=$MODELS"

echo "--- sync sampled posters only ---"
aws s3 sync "$STAGE/posters/" "s3://${BUCKET}/${PREFIX}/posters/" --size-only

echo "LISTO — s3://${BUCKET}/${PREFIX}/"
echo "Siguiente: MODELS=qwen,qwen7 bash aws/launch_ocr_qwen_hard.sh"
