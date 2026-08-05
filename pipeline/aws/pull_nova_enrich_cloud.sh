#!/usr/bin/env bash
# Pull cloud Nova enrich results and merge into local nova_enrich.csv
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-sandbox}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export AWS_EC2_METADATA_DISABLED=true

BUCKET="${NOVA_ENRICH_S3_BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${NOVA_ENRICH_S3_PREFIX:-wflike-nova-enrich/cloud}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL="$PIPE/data/qa/nova_enrich"
DEST="s3://${BUCKET}/${PREFIX}"

mkdir -p "$LOCAL/json" "$LOCAL/cloud_rows" "$LOCAL/cloud_results"

echo "=== pull ${DEST} ==="
aws s3 sync "${DEST}/json" "$LOCAL/json" --only-show-errors
# Optional shard CSVs (future); no-op / soft-fail if prefix missing
aws s3 sync "${DEST}/rows" "$LOCAL/cloud_rows" --only-show-errors || true
aws s3 cp "${DEST}/progress_cloud.json" "$LOCAL/progress_cloud.json" --only-show-errors || true

# Canonical CSV at prefix root (nova_enrich_ec2_chain sync_results)
ROOT_CSV="$LOCAL/cloud_nova_enrich.csv"
if aws s3 ls "${DEST}/nova_enrich.csv" >/dev/null 2>&1; then
  aws s3 cp "${DEST}/nova_enrich.csv" "$ROOT_CSV" --only-show-errors
  echo "downloaded ${DEST}/nova_enrich.csv -> ${ROOT_CSV}"
else
  echo "no root nova_enrich.csv at ${DEST}/ (will merge rows/ only if present)"
  rm -f "$ROOT_CSV"
fi

# DONE / log / errors from EC2 chain
aws s3 sync "${DEST}/results" "$LOCAL/cloud_results" --only-show-errors || true

csv_path="$LOCAL/nova_enrich.csv"
if [ -f "$csv_path" ] && [ -s "$csv_path" ]; then
  bak="$LOCAL/nova_enrich.csv.bak_pre_pull_$(date -u +%Y%m%dT%H%M%SZ)"
  cp "$csv_path" "$bak"
  echo "backup $bak"
fi

python3 - <<PY
import csv
from pathlib import Path

local = Path(r"""$LOCAL""")
csv_path = local / "nova_enrich.csv"
rows_dir = local / "cloud_rows"
root_csv = local / "cloud_nova_enrich.csv"
fields = None
by_id = {}
added = updated = 0


def merge_rows(path: Path, *, canonical: bool = False) -> None:
    """Merge CSV into by_id. canonical=True: cloud root always wins on id."""
    global fields, added, updated
    with path.open(encoding="utf-8", errors="replace") as f:
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
                continue
            if canonical:
                by_id[pid] = row
                updated += 1
                continue
            if str(prev.get("status")) != "ok" and str(row.get("status")) == "ok":
                by_id[pid] = row
                updated += 1
            elif str(prev.get("status")) == "ok":
                pass
            else:
                by_id[pid] = row
                updated += 1


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

if root_csv.exists() and root_csv.stat().st_size > 0:
    a0, u0 = added, updated
    merge_rows(root_csv, canonical=True)
    print(
        f"merged canonical root CSV {root_csv.name} "
        f"(+{added - a0} add / {updated - u0} upd)"
    )

for p in sorted(rows_dir.glob("*.csv")):
    merge_rows(p, canonical=False)

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
