#!/bin/bash
# Pull OWLv2 backfill (+ weapons) from S3 and merge into local creature_boxes.
#
# Usage:
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/pull_owlv2_backfill.sh          # wait for DONE then pull+merge
#   bash pipeline/aws/pull_owlv2_backfill.sh --now    # pull whatever is there
#   bash pipeline/aws/pull_owlv2_backfill.sh --merge-only
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-aof-owlv2-102516364259}"
PREFIX="${PREFIX:-wflike-owlv2-backfill}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
QA=data/qa/owlv2_backfill
mkdir -p "$QA/pull"

WAIT=1
MERGE_ONLY=0
for a in "$@"; do
  [ "$a" = "--now" ] && WAIT=0
  [ "$a" = "--merge-only" ] && MERGE_ONLY=1 && WAIT=0
done

if [ "$MERGE_ONLY" -eq 0 ]; then
  if [ "$WAIT" -eq 1 ]; then
    echo "waiting for s3://${BUCKET}/${PREFIX}/results/DONE …"
    while true; do
      if aws s3 ls "s3://${BUCKET}/${PREFIX}/results/DONE" >/dev/null 2>&1; then
        break
      fi
      if aws s3 ls "s3://${BUCKET}/${PREFIX}/results/FAIL" >/dev/null 2>&1; then
        echo "FAIL marker present — pulling partial results"
        aws s3 cp "s3://${BUCKET}/${PREFIX}/results/FAIL" "$QA/pull/FAIL" || true
        break
      fi
      aws s3 cp "s3://${BUCKET}/${PREFIX}/results/PROGRESS" - 2>/dev/null || echo "(no PROGRESS yet)"
      sleep 60
    done
  fi

  echo "--- pull results ---"
  aws s3 cp "s3://${BUCKET}/${PREFIX}/results/creature_boxes_delta.json" \
    "$QA/pull/creature_boxes_delta.json" || true
  aws s3 cp "s3://${BUCKET}/${PREFIX}/results/weapon_boxes.json" \
    "$QA/pull/weapon_boxes.json" || true
  aws s3 cp "s3://${BUCKET}/${PREFIX}/results/owlv2_backfill_aws.log" \
    "$QA/pull/owlv2_backfill_aws.log" 2>/dev/null || true
  aws s3 cp "s3://${BUCKET}/${PREFIX}/results/PROGRESS" "$QA/pull/PROGRESS" 2>/dev/null || true
  aws s3 cp "s3://${BUCKET}/${PREFIX}/results/DONE" "$QA/pull/DONE" 2>/dev/null || true
fi

if [ ! -f "$QA/pull/creature_boxes_delta.json" ]; then
  echo "missing $QA/pull/creature_boxes_delta.json"; exit 1
fi

echo "--- merge (append-only into creature_boxes; weapons sidecar) ---"
python3 <<'PY'
import json
import shutil
from pathlib import Path
from datetime import datetime

DATA = Path("data")
SITE = Path("../site/data")
QA = DATA / "qa" / "owlv2_backfill" / "pull"

creature_path = DATA / "creature_boxes.json"
weapon_path = DATA / "weapon_boxes.json"
delta_path = QA / "creature_boxes_delta.json"
w_pull = QA / "weapon_boxes.json"

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
bak = DATA / "qa" / "owlv2_backfill" / f"creature_boxes.bak_{ts}.json"
bak.parent.mkdir(parents=True, exist_ok=True)
if creature_path.exists():
    shutil.copy2(creature_path, bak)
    print(f"backup → {bak}")

existing = json.loads(creature_path.read_text(encoding="utf-8")) if creature_path.exists() else {}
delta = json.loads(delta_path.read_text(encoding="utf-8"))
added = skipped = 0
for k, v in delta.items():
    if k in existing:
        skipped += 1
        continue
    existing[k] = v
    added += 1

creature_path.write_text(
    json.dumps({str(k): existing[k] for k in sorted(existing, key=lambda x: int(x))}, ensure_ascii=False),
    encoding="utf-8",
)
print(f"creature_boxes: total={len(existing)} added={added} skipped_existing={skipped}")

# site js
SITE.mkdir(parents=True, exist_ok=True)
payload = json.dumps({str(k): existing[k] for k in sorted(existing, key=lambda x: int(x))}, ensure_ascii=False)
(SITE / "creature_boxes.js").write_text(
    "/* OWLv2 creature boxes — pipeline/owlv2_creature_boxes.py */\n"
    f"window.CREATURE_BOXES={payload};\n",
    encoding="utf-8",
)
print(f"wrote {SITE / 'creature_boxes.js'}")

if w_pull.exists():
    # Merge weapons (prefer newer pull for overlapping keys)
    local_w = json.loads(weapon_path.read_text(encoding="utf-8")) if weapon_path.exists() else {}
    remote_w = json.loads(w_pull.read_text(encoding="utf-8"))
    before = len(local_w)
    local_w.update(remote_w)
    weapon_path.write_text(
        json.dumps({str(k): local_w[k] for k in sorted(local_w, key=lambda x: int(x))}, ensure_ascii=False),
        encoding="utf-8",
    )
    wpayload = json.dumps({str(k): local_w[k] for k in sorted(local_w, key=lambda x: int(x))}, ensure_ascii=False)
    (SITE / "weapon_boxes.js").write_text(
        "/* OWLv2 weapon boxes — pipeline/owlv2_creature_boxes.py */\n"
        f"window.WEAPON_BOXES={wpayload};\n",
        encoding="utf-8",
    )
    print(f"weapon_boxes: total={len(local_w)} (was {before}, pull={len(remote_w)})")
    print(f"wrote {SITE / 'weapon_boxes.js'}")
else:
    print("no weapon_boxes.json in pull — skip weapon merge")

summary = {
    "creature_total": len(existing),
    "creature_added": added,
    "creature_skipped": skipped,
    "weapon_total": len(json.loads(weapon_path.read_text())) if weapon_path.exists() else 0,
}
(QA / "merge_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2))
PY

echo "LISTO — merge done. Optional: wire weapon_boxes.js into site/index.html when ready."
