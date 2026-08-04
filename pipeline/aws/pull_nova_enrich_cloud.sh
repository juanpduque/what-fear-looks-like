#!/usr/bin/env bash
# Pull cloud Nova enrich results and merge into local nova_enrich.csv
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-sandbox}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export AWS_EC2_METADATA_DISABLED=true

BUCKET="${NOVA_ENRICH_S3_BUCKET:-strands-travelagents3sessionsbucket-sn8rc9ezuma6}"
PREFIX="${NOVA_ENRICH_S3_PREFIX:-wflike-nova-enrich/cloud}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL="$PIPE/data/qa/nova_enrich"
DEST="s3://${BUCKET}/${PREFIX}"

mkdir -p "$LOCAL/json" "$LOCAL/cloud_rows"

echo "=== pull ${DEST} ==="
aws s3 sync "${DEST}/json" "$LOCAL/json" --only-show-errors
aws s3 sync "${DEST}/rows" "$LOCAL/cloud_rows" --only-show-errors
aws s3 cp "${DEST}/progress_cloud.json" "$LOCAL/progress_cloud.json" --only-show-errors || true

python3 - <<PY
import csv
from pathlib import Path

local = Path(r"""$LOCAL""")
csv_path = local / "nova_enrich.csv"
rows_dir = local / "cloud_rows"
fields = None
by_id = {}

if csv_path.exists() and csv_path.stat().st_size > 0:
    with csv_path.open(encoding="utf-8", errors="replace") as f:
        r = csv.DictReader(f)
        fields = r.fieldnames
        for row in r:
            try:
                pid = int(row["id"])
            except (TypeError, ValueError):
                continue
            by_id[pid] = row

added = updated = 0
for p in sorted(rows_dir.glob("*.csv")):
    with p.open(encoding="utf-8", errors="replace") as f:
        rr = csv.DictReader(f)
        if not fields:
            fields = rr.fieldnames
        for row in rr:
            try:
                pid = int(row["id"])
            except (TypeError, ValueError):
                continue
            prev = by_id.get(pid)
            if prev is None:
                by_id[pid] = row
                added += 1
            elif str(prev.get("status")) != "ok" and str(row.get("status")) == "ok":
                by_id[pid] = row
                updated += 1
            elif str(prev.get("status")) == "ok":
                pass
            else:
                by_id[pid] = row
                updated += 1

fields = list(fields or [])
out_rows = [by_id[k] for k in sorted(by_id)]
with csv_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for row in out_rows:
        w.writerow(row)
ok = sum(1 for r in out_rows if str(r.get("status")) == "ok")
print(f"merged added={added} updated={updated} total_rows={len(out_rows)} ok={ok}")
print(f"wrote {csv_path}")
PY

echo "=== pull complete ==="
