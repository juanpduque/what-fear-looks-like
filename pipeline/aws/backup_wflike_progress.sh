#!/usr/bin/env bash
# Periodic backup of Nova enrich + Textract OCR progress to workshop S3.
#   export AWS_PROFILE=sandbox
#   bash pipeline/aws/backup_wflike_progress.sh
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-sandbox}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy || true

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
BUCKET="${WFLIKE_BACKUP_BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${WFLIKE_BACKUP_PREFIX:-wflike-backup/$(date +%Y%m%d)}"
INTERVAL="${WFLIKE_BACKUP_INTERVAL:-300}"
DEST="s3://${BUCKET}/${PREFIX}"
LOG="$PIPE/data/qa/wflike_s3_backup.log"

mkdir -p "$(dirname "$LOG")"
echo "$(date '+%Y-%m-%d %H:%M:%S') backup loop start interval=${INTERVAL}s dest=${DEST}" | tee -a "$LOG"

backup_once() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  # Nova enrich
  local nova="$PIPE/data/qa/nova_enrich"
  for f in nova_enrich.csv progress.json nova_enrich.log RESUME.txt live_summary.md live_summary.json; do
    [[ -f "$nova/$f" ]] && aws s3 cp "$nova/$f" "${DEST}/nova_enrich/$f" --only-show-errors || true
  done
  if [[ -d "$nova/json" ]]; then
    aws s3 sync "$nova/json" "${DEST}/nova_enrich/json" --only-show-errors || true
  fi
  # Textract OCR
  for f in poster_ocr_textract.csv poster_ocr_textract_partial.csv poster_ocr_textract_run.log; do
    [[ -f "$PIPE/data/$f" ]] && aws s3 cp "$PIPE/data/$f" "${DEST}/textract/$f" --only-show-errors || true
  done
  # DetectText / Comprehend / QA if present
  for f in poster_ocr_rek_text.csv poster_ocr_rek_text_partial.csv \
           poster_ocr_rek_text_alllang.csv poster_ocr_rek_text_alllang_partial.csv \
           ocr_comprehend.csv ocr_comprehend_partial.csv \
           nova_qa_sample.csv nova_qa_sample.jsonl \
           nova_qa_large.csv nova_qa_large.jsonl \
           nova_qa_sonnet.csv nova_qa_sonnet.jsonl \
           nova_qa_maverick.csv nova_qa_maverick.jsonl \
           rek_text_alllang_ids.txt rek_text_alllang_manifest.csv; do
    [[ -f "$PIPE/data/$f" ]] && aws s3 cp "$PIPE/data/$f" "${DEST}/extra/$f" --only-show-errors || true
    [[ -f "$PIPE/data/qa/$f" ]] && aws s3 cp "$PIPE/data/qa/$f" "${DEST}/extra/$f" --only-show-errors || true
  done
  [[ -f "$PIPE/data/poster_ocr.csv" ]] && aws s3 cp "$PIPE/data/poster_ocr.csv" "${DEST}/extra/poster_ocr_easyocr.csv" --only-show-errors || true
  # community set
  for f in community_manifest.csv README.md; do
    [[ -f "$PIPE/data/community/$f" ]] && aws s3 cp "$PIPE/data/community/$f" "${DEST}/community/$f" --only-show-errors || true
  done
  for f in poster_ocr_textract_alllang.csv poster_ocr_textract_alllang_partial.csv \
           ocr_comprehend_alllang.csv ocr_comprehend_alllang_partial.csv; do
    [[ -f "$PIPE/data/$f" ]] && aws s3 cp "$PIPE/data/$f" "${DEST}/extra/$f" --only-show-errors || true
  done
  # Title-match / drift review / multi-poster swaps (critical QA)
  local qa="$PIPE/data/qa"
  for f in poster_title_match.csv poster_title_match_suspects.csv \
           poster_title_match_drift_review.csv poster_title_match_drift_review.jsonl \
           poster_title_match_drift_sample_ids.csv \
           poster_title_match_drift_review_haiku.csv poster_title_match_drift_review_sonnet.csv \
           poster_title_match_drift_review_pro_snapshot.csv poster_title_match_drift_review_lite_snapshot.csv \
           poster_title_mismatch_consensus.csv \
           multi_poster_variant_ocr_scores.csv multi_poster_variant_ocr_swaps.csv \
           multi_poster_variant_ocr_swaps_applied.csv multi_poster_variant_ocr_swaps_reanalyze_ids.csv \
           multi_poster_canonical_mismatch.csv multi_poster_catalog_mismatch_only.csv \
           primary_drift_applied.csv primary_drift_reanalyze_ids.csv \
           medium_qa_r3_labels.json medium_qa_r3_ids.csv \
           typography_qa_r1_labels.json typography_qa_r1_ids.csv \
           label_qa_medium_train.csv; do
    [[ -f "$qa/$f" ]] && aws s3 cp "$qa/$f" "${DEST}/qa/$f" --only-show-errors || true
    [[ -f "$PIPE/data/$f" ]] && aws s3 cp "$PIPE/data/$f" "${DEST}/qa/$f" --only-show-errors || true
  done
  # medium custom-labels prep artifacts (no secrets)
  if [[ -d "$qa/medium_custom_labels" ]]; then
    for f in gold_merged.csv split.csv logreg_metrics.json prepare.json custom_labels_run.json compare_f1.json; do
      [[ -f "$qa/medium_custom_labels/$f" ]] && \
        aws s3 cp "$qa/medium_custom_labels/$f" "${DEST}/qa/medium_custom_labels/$f" --only-show-errors || true
    done
  fi
  # runtime residual fill (inventory + fills; skip any .env)
  if [[ -d "$qa/runtime_residual_fill" ]]; then
    for f in SUMMARY.md summary.json summary_omdb.json fills.csv still_zero.csv \
             inventory_before.json need_imdb_features_ids.csv \
             imdb_suggest_features_miss_residual.csv run.log; do
      [[ -f "$qa/runtime_residual_fill/$f" ]] && \
        aws s3 cp "$qa/runtime_residual_fill/$f" "${DEST}/qa/runtime_residual_fill/$f" --only-show-errors || true
    done
  fi
  # IMDb scrap / selenium results if present locally
  for f in imdb_poster_hits.csv imdb_poster_miss.csv imdb_poster_ids.csv \
           imdb_selenium_features_miss.csv; do
    [[ -f "$PIPE/data/$f" ]] && aws s3 cp "$PIPE/data/$f" "${DEST}/imdb/$f" --only-show-errors || true
  done
  if [[ -d "$PIPE/data/imdb_selenium_s3_pull" ]]; then
    for f in imdb_selenium_pilot_hits.csv imdb_selenium_pilot_miss.csv \
             gap_en_need_imdb_live.csv imdb_ids.csv IMDB_SELENIUM_DONE imdb_selenium_S3_UPLOADED; do
      [[ -f "$PIPE/data/imdb_selenium_s3_pull/$f" ]] && \
        aws s3 cp "$PIPE/data/imdb_selenium_s3_pull/$f" "${DEST}/imdb/selenium_pull/$f" --only-show-errors || true
    done
  fi
  # Explicitly never upload secrets
  # (skip .env, credentials, OMDB keys — not listed above)
  # stamped nova csv
  if [[ -f "$nova/nova_enrich.csv" ]]; then
    stamp="$(date +%Y%m%d_%H%M%S)"
    aws s3 cp "$nova/nova_enrich.csv" "${DEST}/nova_enrich/snapshots/nova_enrich_${stamp}.csv" --only-show-errors || true
  fi
  nova_ok="?"
  tex_n="?"
  if [[ -f "$nova/nova_enrich.csv" ]]; then
    nova_ok="$(python3 -c "import csv;print(sum(1 for r in csv.DictReader(open('$nova/nova_enrich.csv')) if r.get('status')=='ok'))" 2>/dev/null || echo '?')"
  fi
  if [[ -f "$PIPE/data/poster_ocr_textract_partial.csv" ]]; then
    tex_n="$(python3 -c "print(sum(1 for _ in open('$PIPE/data/poster_ocr_textract_partial.csv'))-1)" 2>/dev/null || echo '?')"
  fi
  echo "$ts backup nova_ok=${nova_ok} textract_rows=${tex_n} → ${DEST}" | tee -a "$LOG"
}

backup_once
if [[ "${WFLIKE_BACKUP_ONCE:-0}" == "1" ]]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') backup once done" | tee -a "$LOG"
  exit 0
fi
while true; do
  sleep "$INTERVAL"
  backup_once
done
