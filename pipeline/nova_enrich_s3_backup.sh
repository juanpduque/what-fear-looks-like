#!/usr/bin/env bash
# Periodic local→S3 backup for nova enrich outputs (no Bedrock).
# Does not interrupt the enrich worker.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-sandbox}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export AWS_EC2_METADATA_DISABLED=true

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOCAL="$ROOT/data/qa/nova_enrich"
BUCKET="${NOVA_ENRICH_S3_BUCKET:-strands-travelagents3bucketrag-tnkrjps7ufqv}"
PREFIX="${NOVA_ENRICH_S3_PREFIX:-wflike-nova-enrich/$(date +%Y%m%d)}"
INTERVAL="${NOVA_ENRICH_BACKUP_INTERVAL:-300}"  # seconds
LOG="$LOCAL/s3_backup.log"

mkdir -p "$LOCAL"
DEST="s3://${BUCKET}/${PREFIX}"

echo "$(date '+%Y-%m-%d %H:%M:%S') backup loop start interval=${INTERVAL}s dest=${DEST}" | tee -a "$LOG"

backup_once() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  # core state files
  for f in nova_enrich.csv progress.json RESUME_STATE.json RESUME.txt live_summary.md live_summary.json nova_enrich.log; do
    if [[ -f "$LOCAL/$f" ]]; then
      aws s3 cp "$LOCAL/$f" "${DEST}/$f" --only-show-errors --region "$AWS_DEFAULT_REGION" || true
    fi
  done
  # json directory (incremental sync)
  if [[ -d "$LOCAL/json" ]]; then
    aws s3 sync "$LOCAL/json" "${DEST}/json" --only-show-errors --region "$AWS_DEFAULT_REGION" || true
  fi
  # stamped copy of csv for history
  if [[ -f "$LOCAL/nova_enrich.csv" ]]; then
    stamp="$(date +%Y%m%d_%H%M%S)"
    aws s3 cp "$LOCAL/nova_enrich.csv" "${DEST}/snapshots/nova_enrich_${stamp}.csv" --only-show-errors --region "$AWS_DEFAULT_REGION" || true
  fi
  ok="?"
  if [[ -f "$LOCAL/nova_enrich.csv" ]]; then
    ok="$(python3 -c "import csv;print(sum(1 for r in csv.DictReader(open('$LOCAL/nova_enrich.csv')) if r.get('status')=='ok'))" 2>/dev/null || echo '?')"
  fi
  echo "$ts backup ok_rows=${ok} → ${DEST}" | tee -a "$LOG"
}

backup_once
while true; do
  sleep "$INTERVAL"
  backup_once
done
