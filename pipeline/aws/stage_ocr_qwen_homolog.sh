#!/bin/bash
# Stage Qwen OCR on homolog posters (same sample as ocr_pilot_v2, filtered to
# ids that exist in posters_homolog).
#
# Copies sample_ids from ocr_pilot_v2, stages code + true 1000×1500 homolog JPGs
# only from local posters_homolog or s3://…/posters_homolog/{id}.jpg.
# NEVER invents / letterboxes from w342 or other non-homolog sources.
#
# Usage:
#   bash aws/stage_ocr_qwen_homolog.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-ocr_qwen_homolog}"
SRC_PREFIX="${SRC_PREFIX:-ocr_pilot_v2}"
MAX_N="${MAX_N:-120}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

echo "=== stage_${PREFIX} → s3://$BUCKET/${PREFIX}/ ==="

mkdir -p "data/qa/${PREFIX}"

# Same pilot sample as ocr_pilot_v2 (may be filtered to homolog coverage below)
if [ ! -f "data/qa/${PREFIX}/sample_ids.txt" ]; then
  if [ -f "data/qa/${SRC_PREFIX}/sample_ids.txt" ]; then
    cp -f "data/qa/${SRC_PREFIX}/sample_ids.txt" "data/qa/${PREFIX}/sample_ids.txt"
    cp -f "data/qa/${SRC_PREFIX}/sample_meta.csv" "data/qa/${PREFIX}/sample_meta.csv" 2>/dev/null || true
  else
    echo "--- pulling sample from s3://${BUCKET}/${SRC_PREFIX}/ ---"
    aws s3 cp "s3://${BUCKET}/${SRC_PREFIX}/sample_ids.txt" "data/qa/${PREFIX}/sample_ids.txt"
    aws s3 cp "s3://${BUCKET}/${SRC_PREFIX}/sample_meta.csv" \
      "data/qa/${PREFIX}/sample_meta.csv" 2>/dev/null || true
  fi
fi

N_LOCAL=$(wc -l < "data/qa/${PREFIX}/sample_ids.txt" | tr -d ' ')
if [ "$N_LOCAL" -gt "$MAX_N" ]; then
  echo "ERROR: sample has $N_LOCAL ids — refuse >$MAX_N"; exit 1
fi
if [ "$N_LOCAL" -lt 1 ]; then
  echo "ERROR: empty sample_ids.txt"; exit 1
fi
echo "sample_n=$N_LOCAL (from ${SRC_PREFIX} / existing ${PREFIX})"

STAGE="data/qa/_${PREFIX}_stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/code" "$STAGE/posters" "$STAGE/qa"

cp -f pilot_ocr_models.py "$STAGE/code/pilot_ocr_models.py"
cp -f ocr_metrics.py "$STAGE/code/ocr_metrics.py"
cp -f aws/ocr_qwen_homolog_chain.sh "$STAGE/code/ocr_qwen_homolog_chain.sh"
cp -f aws/ocr_qwen_homolog_userdata.sh "$STAGE/code/ocr_qwen_homolog_userdata.sh"

python3 - <<PY
"""Stage ONLY true homolog JPGs (local or S3 posters_homolog). No w342 letterbox."""
from pathlib import Path
import os
import shutil
import subprocess

import pandas as pd

prefix = "${PREFIX}"
bucket = "${BUCKET}"
max_n = int("${MAX_N}")
qa = Path(f"data/qa/{prefix}")
ids_path = qa / "sample_ids.txt"
ids = [int(x) for x in ids_path.read_text().split() if x.strip()]
stage = Path(f"data/qa/_{prefix}_stage")
dst = stage / "posters"
hom = Path("data/posters_homolog")


def link_or_copy(src: Path, d: Path) -> None:
    try:
        os.link(src, d)
    except OSError:
        shutil.copy2(src, d)


def pull_s3_homolog(pid: int, d: Path) -> bool:
    r = subprocess.run(
        [
            "aws", "s3", "cp",
            f"s3://{bucket}/posters_homolog/{pid}.jpg",
            str(d),
        ],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and d.exists() and d.stat().st_size > 1000


ok_ids = []
from_local = from_s3 = miss = 0
missing = []
for pid in ids:
    d = dst / f"{pid}.jpg"
    s = hom / f"{pid}.jpg"
    if s.exists() and s.stat().st_size > 1000:
        link_or_copy(s, d)
        ok_ids.append(pid)
        from_local += 1
        continue
    if pull_s3_homolog(pid, d):
        ok_ids.append(pid)
        from_s3 += 1
        continue
    miss += 1
    missing.append(pid)
    print(f"MISSING true homolog id={pid}", flush=True)

print(
    f"true_homolog={len(ok_ids)} from_local={from_local} from_s3={from_s3} "
    f"missing={miss} (of sample {len(ids)})",
    flush=True,
)

if miss:
    # Keep pilot∩homolog only — never invent from w342. Rewrite sample to ok_ids.
    if not ok_ids:
        raise SystemExit("incomplete stage: 0 true homologs — abort")
    print(
        f"WARNING: dropping {miss} ids without posters_homolog; "
        f"continuing with n={len(ok_ids)} true homologs for valid A/B",
        flush=True,
    )
    # Preserve original pilot sample for audit
    pilot_bak = qa / "sample_ids_pilot_full.txt"
    if not pilot_bak.exists():
        pilot_bak.write_text(ids_path.read_text())
        print(f"saved full pilot sample → {pilot_bak}", flush=True)
    ids_path.write_text("\n".join(str(i) for i in ok_ids) + "\n")
    meta = qa / "sample_meta.csv"
    if meta.exists():
        try:
            m = pd.read_csv(meta)
            idcol = "id" if "id" in m.columns else m.columns[0]
            m = m[m[idcol].astype(int).isin(ok_ids)]
            m.to_csv(meta, index=False)
        except Exception as e:
            print(f"WARNING: could not filter sample_meta.csv: {e}", flush=True)
    ids = ok_ids

if not ids:
    raise SystemExit("no posters staged")
if len(ids) > max_n:
    raise SystemExit(f"refuse staging {len(ids)} > {max_n}")

p = pd.read_csv("data/posters.csv")
p = p[p["id"].astype(int).isin(ids)]
p.to_csv(stage / "posters.csv", index=False)
print(f"posters.csv subset rows={len(p)} ids={len(ids)}")

# Final integrity: every staged jpg must match S3 or local homolog byte-size
bad = 0
for pid in ids:
    d = dst / f"{pid}.jpg"
    if not d.exists() or d.stat().st_size <= 1000:
        print(f"ERROR staged missing/small id={pid}", flush=True)
        bad += 1
if bad:
    raise SystemExit(f"integrity fail: {bad} bad staged jpgs")

shutil.copy2(ids_path, stage / "qa" / "sample_ids.txt")
meta = qa / "sample_meta.csv"
if meta.exists():
    shutil.copy2(meta, stage / "qa" / "sample_meta.csv")

print(f"staged jpgs={len(ids)} (true homolog only)", flush=True)
PY

# Ensure qa copies after python may have rewritten sample
cp -f "data/qa/${PREFIX}/sample_ids.txt" "$STAGE/qa/sample_ids.txt"
[ -f "data/qa/${PREFIX}/sample_meta.csv" ] && \
  cp -f "data/qa/${PREFIX}/sample_meta.csv" "$STAGE/qa/sample_meta.csv"

N_LOCAL=$(wc -l < "data/qa/${PREFIX}/sample_ids.txt" | tr -d ' ')
echo "final sample_n=$N_LOCAL"
echo "jpg count: $(ls "$STAGE/posters"/*.jpg 2>/dev/null | wc -l | tr -d ' ')"

echo "--- upload code + ids + subset posters.csv ---"
aws s3 cp "$STAGE/code/pilot_ocr_models.py" "s3://${BUCKET}/${PREFIX}/code/pilot_ocr_models.py"
aws s3 cp "$STAGE/code/ocr_metrics.py" "s3://${BUCKET}/${PREFIX}/code/ocr_metrics.py"
aws s3 cp "$STAGE/code/ocr_qwen_homolog_chain.sh" "s3://${BUCKET}/${PREFIX}/code/ocr_qwen_homolog_chain.sh"
aws s3 cp "$STAGE/code/ocr_qwen_homolog_userdata.sh" "s3://${BUCKET}/${PREFIX}/code/ocr_qwen_homolog_userdata.sh"
aws s3 cp "$STAGE/qa/sample_ids.txt" "s3://${BUCKET}/${PREFIX}/sample_ids.txt"
aws s3 cp "$STAGE/posters.csv" "s3://${BUCKET}/${PREFIX}/posters.csv"
[ -f "$STAGE/qa/sample_meta.csv" ] && aws s3 cp "$STAGE/qa/sample_meta.csv" "s3://${BUCKET}/${PREFIX}/sample_meta.csv"

MODELS="${MODELS:-qwen}"
printf '%s\n' "$MODELS" | aws s3 cp - "s3://${BUCKET}/${PREFIX}/MODELS"
echo "staged MODELS=$MODELS"

echo "--- sync sampled homolog posters only ---"
aws s3 sync "$STAGE/posters/" "s3://${BUCKET}/${PREFIX}/posters/" --size-only

echo "LISTO — s3://${BUCKET}/${PREFIX}/"
echo "Siguiente: MODELS=qwen bash aws/launch_ocr_qwen_homolog.sh"
