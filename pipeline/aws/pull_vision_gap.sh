#!/bin/bash
# Pull vision-gap results from S3 into pipeline/data/ (merge-safe: prefer larger unique id count).
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy || true

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-vision-gap}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa/vision_gap/pull

echo "=== pull s3://$BUCKET/$PREFIX/results/ ==="
aws s3 sync "s3://${BUCKET}/${PREFIX}/results/" data/qa/vision_gap/pull/results/
aws s3 cp "s3://${BUCKET}/${PREFIX}/results/PROGRESS.json" data/qa/vision_gap/PROGRESS.json 2>/dev/null || true
aws s3 cp "s3://${BUCKET}/${PREFIX}/results/DONE" data/qa/vision_gap/DONE 2>/dev/null || true

python3 - <<'PY'
"""Merge pulled CSVs/npz into pipeline/data if they have more unique ids."""
from pathlib import Path
import shutil
import pandas as pd
import numpy as np

PULL = Path("data/qa/vision_gap/pull/results")
DATA = Path("data")

def n_csv(p: Path) -> int:
    if not p.exists():
        return 0
    try:
        return int(pd.read_csv(p, usecols=["id"])["id"].nunique())
    except Exception:
        return 0

def merge_csv(name: str):
    src = PULL / name
    dst = DATA / name
    if not src.exists():
        print(f"skip {name}: no pull")
        return
    ns, nd = n_csv(src), n_csv(dst)
    if ns >= nd and ns > 0:
        # union if both exist
        if dst.exists() and nd > 0:
            a = pd.read_csv(src); b = pd.read_csv(dst)
            a["id"] = a["id"].astype(int); b["id"] = b["id"].astype(int)
            m = pd.concat([b, a]).drop_duplicates("id", keep="last")
            m.to_csv(dst, index=False)
            print(f"{name}: merged pull={ns} local={nd} -> {len(m)}")
        else:
            shutil.copy2(src, dst)
            print(f"{name}: replaced local={nd} <- pull={ns}")
    else:
        print(f"{name}: keep local={nd} (pull={ns})")

for name in [
    "faces_v2.csv", "attributes.csv", "census.csv", "typography.csv",
    "medium.csv", "segmentation.csv",
    "faces_v2_partial.csv", "attributes_partial.csv", "segmentation_partial.csv",
]:
    merge_csv(name)

# decade/yearly jsons: take pull if present
for name in [
    "faces_v2_decade.json", "attributes_decade.json", "census_decade.json",
    "typography_decade.json", "medium_yearly.json", "segmentation_decade.json",
]:
    src, dst = PULL / name, DATA / name
    if src.exists():
        shutil.copy2(src, dst)
        print(f"{name}: copied")

# embeddings: prefer larger
src, dst = PULL / "clip_embeddings.npz", DATA / "clip_embeddings.npz"
if src.exists():
    ns = len(np.load(src)["ids"])
    nd = len(np.load(dst)["ids"]) if dst.exists() else 0
    if ns >= nd:
        shutil.copy2(src, dst)
        print(f"clip_embeddings.npz: {nd} -> {ns}")
    else:
        print(f"clip_embeddings.npz: keep {nd} (pull {ns})")

print("DONE pull/merge")
PY
