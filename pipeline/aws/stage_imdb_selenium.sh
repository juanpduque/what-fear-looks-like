#!/bin/bash
# Stage IMDb Selenium job to workshop S3 (sandbox defaults).
#
# Usage:
#   export AWS_PROFILE=sandbox
#   export TMDB_API_KEY=...
#   bash pipeline/aws/stage_imdb_selenium.sh
#   MODE=ambiguous bash pipeline/aws/stage_imdb_selenium.sh
#   bash pipeline/aws/stage_imdb_selenium.sh --dry-run
#
# Then: bash pipeline/aws/launch_imdb_selenium.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-imdb-selenium}"
MODE="${MODE:-features}"
LIMIT="${LIMIT:-0}"
DELAY="${DELAY:-1.4}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"

DRY=0
for a in "$@"; do
  [ "$a" = "--dry-run" ] && DRY=1
done

echo "=== stage_imdb_selenium → s3://${BUCKET}/${PREFIX}/ MODE=$MODE ==="

need=(
  enrich_imdb_selenium_features.py
  resolve_imdb_ambiguous_selenium.py
  enrich_imdb_ids.py
  match_imdb_title_basics_features.py
  aws/imdb_selenium_chain.sh
  aws/imdb_selenium_userdata.sh
)
if [ "$MODE" = "posters" ]; then
  need+=(pull_imdb_posters.py)
fi
for f in "${need[@]}"; do
  if [ ! -f "$f" ]; then
    echo "missing $f"; exit 1
  fi
done

if [ -z "${TMDB_API_KEY:-}" ]; then
  echo "WARNING: TMDB_API_KEY not set — stage will skip secret upload"
  echo "  Set it before launch or put key in data/qa/tmdb_api_key"
fi

STAGE=data/qa/_imdb_selenium_stage
rm -rf "$STAGE"
mkdir -p "$STAGE/code/aws" "$STAGE/input/qa" "$STAGE/results"

cp -f enrich_imdb_selenium_features.py "$STAGE/code/"
cp -f resolve_imdb_ambiguous_selenium.py "$STAGE/code/"
cp -f enrich_imdb_ids.py "$STAGE/code/"
cp -f match_imdb_title_basics_features.py "$STAGE/code/"
cp -f aws/imdb_selenium_chain.sh "$STAGE/code/aws/"
cp -f aws/imdb_selenium_userdata.sh "$STAGE/code/aws/"

# Inputs depending on MODE
case "$MODE" in
  features)
    # Optional: FEATURES_IDS_FILE → staged as imdb_suggest_features_miss.csv (custom residual todo)
    if [ -n "${FEATURES_IDS_FILE:-}" ]; then
      if [ ! -f "$FEATURES_IDS_FILE" ]; then
        echo "ERROR: FEATURES_IDS_FILE missing: $FEATURES_IDS_FILE"; exit 1
      fi
      cp -f "$FEATURES_IDS_FILE" "$STAGE/input/imdb_suggest_features_miss.csv"
      echo "FEATURES_IDS_FILE → input/imdb_suggest_features_miss.csv ($(wc -l < "$FEATURES_IDS_FILE") lines)"
      # Fresh residual run: do not resume prior global hits/miss
      : > "$STAGE/input/imdb_selenium_features_hits.csv"
      : > "$STAGE/input/imdb_selenium_features_miss.csv"
      # headers only for empty resume files
      printf 'id,imdb_id,title,year,director,imdb_directors,match,imdb_year\n' > "$STAGE/input/imdb_selenium_features_hits.csv"
      printf 'id,title,year,director,reason,candidates\n' > "$STAGE/input/imdb_selenium_features_miss.csv"
    else
      for f in imdb_suggest_features_miss.csv imdb_ids.csv \
               imdb_selenium_features_hits.csv imdb_selenium_features_miss.csv; do
        [ -f "data/$f" ] && cp -f "data/$f" "$STAGE/input/$f" || true
      done
    fi
    [ -f data/imdb_ids.csv ] && cp -f data/imdb_ids.csv "$STAGE/input/imdb_ids.csv" || true
    [ -f data/horror_movies.csv ] && \
      echo "(horror_movies.csv too large — not staging full file)" || true
    ;;
  ambiguous)
    for f in imdb_basics_match_features_ambiguous.csv imdb_ids.csv \
             imdb_basics_ambiguous_selenium_hits.csv \
             imdb_basics_ambiguous_selenium_miss.csv; do
      [ -f "data/$f" ] && cp -f "data/$f" "$STAGE/input/$f" || true
    done
    ;;
  posters)
    cp -f pull_imdb_posters.py "$STAGE/code/"
    mkdir -p "$STAGE/input/qa"
    SRC_TODO="${POSTER_IDS_FILE:-data/qa/_poster_funnel_audit/B_imdb_scrap_browser_retry.csv}"
    if [ ! -f "$SRC_TODO" ]; then
      echo "ERROR: missing $SRC_TODO"; exit 1
    fi
    cp -f "$SRC_TODO" "$STAGE/input/qa/imdb_poster_browser_todo.csv"
    for f in imdb_poster_hits.csv imdb_poster_miss.csv imdb_poster_ids.csv; do
      [ -f "data/$f" ] && cp -f "data/$f" "$STAGE/input/$f" || true
    done
    # chain looks under data/qa/
    mkdir -p "$STAGE/input/qa"
    ;;
  *)
    echo "ERROR: MODE must be features|ambiguous|posters (got $MODE)"; exit 1
    ;;
esac

if [ -n "${TMDB_API_KEY:-}" ]; then
  printf '%s' "$TMDB_API_KEY" > "$STAGE/input/qa/tmdb_api_key"
  chmod 600 "$STAGE/input/qa/tmdb_api_key"
fi

# Runtime ENV for userdata/chain
cat > "$STAGE/ENV" <<EOF
export BUCKET=${BUCKET}
export PREFIX=${PREFIX}
export MODE=${MODE}
export LIMIT=${LIMIT}
export DELAY=${DELAY}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
EOF

echo "staged files:"
find "$STAGE" -type f | sed "s|^$STAGE/|  |"

if [ "$DRY" = "1" ]; then
  echo "DRY RUN — not uploading"
  exit 0
fi

echo "--- upload ---"
aws s3 sync "$STAGE/code/" "s3://${BUCKET}/${PREFIX}/code/"
aws s3 sync "$STAGE/input/" "s3://${BUCKET}/${PREFIX}/input/"
aws s3 cp "$STAGE/ENV" "s3://${BUCKET}/${PREFIX}/ENV"
# keep prior results in place (do not wipe)
echo "LISTO stage → s3://${BUCKET}/${PREFIX}/"
echo "Siguiente: MODE=$MODE LIMIT=$LIMIT bash pipeline/aws/launch_imdb_selenium.sh"
