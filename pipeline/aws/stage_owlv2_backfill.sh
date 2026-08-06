#!/bin/bash
# Stage OWLv2 creature backfill + weapon detection to workshop S3.
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/stage_owlv2_backfill.sh
#
# Then: bash pipeline/aws/launch_owlv2_backfill.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-owlv2-backfill}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

echo "=== stage_owlv2_backfill → s3://${BUCKET}/${PREFIX}/ ==="

need=(
  owlv2_creature_boxes.py
  aws/owlv2_backfill_chain.sh
  aws/owlv2_backfill_userdata.sh
  data/attributes.csv
  data/creature_boxes.json
)
for f in "${need[@]}"; do
  if [ ! -f "$f" ]; then
    echo "missing $f"; exit 1
  fi
done

QA=data/qa/owlv2_backfill
STAGE="$QA/_stage"
mkdir -p "$QA" "$STAGE/code/aws" "$STAGE/input" "$STAGE/posters"

echo "--- build ids (attributes − creature_boxes) ---"
python3 <<'PY'
import json
from pathlib import Path
import pandas as pd

DATA = Path("data")
QA = DATA / "qa" / "owlv2_backfill"
POSTERS = DATA / "posters"
attr = set(pd.read_csv(DATA / "attributes.csv", usecols=["id"])["id"].astype(int))
boxes = {int(k) for k in json.loads((DATA / "creature_boxes.json").read_text())}
need = sorted(attr - boxes)
have = [i for i in need if (POSTERS / f"{i}.jpg").exists()]
miss = [i for i in need if i not in set(have)]
QA.mkdir(parents=True, exist_ok=True)
ids_path = QA / "backfill_ids.txt"
ids_path.write_text("\n".join(str(i) for i in have) + ("\n" if have else ""), encoding="utf-8")
meta = {
    "n_attributes": len(attr),
    "n_creature_existing": len(boxes),
    "n_need": len(need),
    "n_with_poster": len(have),
    "n_missing_poster": len(miss),
    "creature_queries": 18,
    "weapon_queries": 12,
}
(QA / "backfill_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
print(json.dumps(meta, indent=2))
if miss[:5]:
    print("missing poster sample:", miss[:5])
if not have:
    raise SystemExit("no posters to stage")
PY

N_IDS=$(wc -l < "$QA/backfill_ids.txt" | tr -d ' ')
echo "ids=$N_IDS"

echo "--- link posters for sync ---"
# Hard-link / copy only needed jpgs into stage dir (size-only sync)
python3 <<'PY'
from pathlib import Path
import os
POSTERS = Path("data/posters")
DST = Path("data/qa/owlv2_backfill/_stage/posters")
ids = [int(x) for x in Path("data/qa/owlv2_backfill/backfill_ids.txt").read_text().split() if x.strip()]
DST.mkdir(parents=True, exist_ok=True)
# Clear stale links not in ids
want = {f"{i}.jpg" for i in ids}
for p in DST.glob("*.jpg"):
    if p.name not in want:
        p.unlink()
n = 0
for i in ids:
    src = POSTERS / f"{i}.jpg"
    dst = DST / f"{i}.jpg"
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        n += 1
        continue
    try:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        os.link(src, dst)
    except OSError:
        import shutil
        shutil.copy2(src, dst)
    n += 1
print(f"staged_poster_links={n}")
PY

cp -f owlv2_creature_boxes.py "$STAGE/code/"
cp -f aws/owlv2_backfill_chain.sh "$STAGE/code/aws/"
cp -f aws/owlv2_backfill_userdata.sh "$STAGE/code/aws/"
cp -f "$QA/backfill_ids.txt" "$STAGE/input/"
cp -f "$QA/backfill_meta.json" "$STAGE/input/"
# Existing creature boxes for protect-list (never overwrite these keys on merge either)
cp -f data/creature_boxes.json "$STAGE/input/creature_boxes_existing.json"

echo "--- upload code + ids ---"
aws s3 cp "$STAGE/code/owlv2_creature_boxes.py" "s3://${BUCKET}/${PREFIX}/code/owlv2_creature_boxes.py"
aws s3 cp "$STAGE/code/aws/owlv2_backfill_chain.sh" "s3://${BUCKET}/${PREFIX}/code/aws/owlv2_backfill_chain.sh"
aws s3 cp "$STAGE/code/aws/owlv2_backfill_userdata.sh" "s3://${BUCKET}/${PREFIX}/code/aws/owlv2_backfill_userdata.sh"
aws s3 cp "$STAGE/input/backfill_ids.txt" "s3://${BUCKET}/${PREFIX}/input/backfill_ids.txt"
aws s3 cp "$STAGE/input/backfill_meta.json" "s3://${BUCKET}/${PREFIX}/input/backfill_meta.json"
aws s3 cp "$STAGE/input/creature_boxes_existing.json" "s3://${BUCKET}/${PREFIX}/input/creature_boxes_existing.json"

echo "--- sync posters (~1GB, size-only) ---"
aws s3 sync "$STAGE/posters/" "s3://${BUCKET}/${PREFIX}/posters/" --size-only

REMOTE=$(aws s3 ls "s3://${BUCKET}/${PREFIX}/posters/" | wc -l | tr -d ' ')
echo "remote_poster_objects=$REMOTE (local_ids=$N_IDS)"
echo "LISTO — bash pipeline/aws/launch_owlv2_backfill.sh"
