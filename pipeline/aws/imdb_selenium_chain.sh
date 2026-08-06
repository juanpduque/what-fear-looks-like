#!/bin/bash
# EC2 chain: headed Chrome via Xvfb → IMDb Selenium enrich → S3 upload.
#
# Env (from userdata / stage):
#   BUCKET, PREFIX, MODE (features|ambiguous), LIMIT, DELAY, TMDB_API_KEY
#
# MODE=features → enrich_imdb_selenium_features.py
# MODE=ambiguous → resolve_imdb_ambiguous_selenium.py
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export NO_PROXY="${NO_PROXY:-*}"
export no_proxy="${no_proxy:-*}"
export BUCKET="${BUCKET:?BUCKET required}"
export PREFIX="${PREFIX:-wflike-imdb-selenium}"
export MODE="${MODE:-features}"
export LIMIT="${LIMIT:-0}"
export DELAY="${DELAY:-1.4}"
export DISPLAY="${DISPLAY:-:99}"
# AWS CLI v2 install path (userdata) + common locations
export PATH="/usr/local/bin:/usr/bin:$PATH"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data aws data/qa

echo "=== imdb_selenium_chain start $(date -u) MODE=$MODE LIMIT=$LIMIT ==="
echo "bucket=s3://${BUCKET}/${PREFIX}/"
if ! command -v aws >/dev/null 2>&1; then
  echo "ERROR: aws CLI not on PATH (expected userdata to install AWS CLI v2)"
  exit 1
fi
echo "aws=$(command -v aws) ($(aws --version 2>&1 | head -1))"

# --- Chrome + Xvfb (idempotent) ---
if ! command -v google-chrome >/dev/null 2>&1 && ! command -v google-chrome-stable >/dev/null 2>&1; then
  echo "--- install Google Chrome ---"
  sudo apt-get update -y
  sudo apt-get install -y wget gnupg unzip xvfb fonts-liberation libnss3 libatk-bridge2.0-0 \
    libgtk-3-0 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2t64 \
    libpangocairo-1.0-0 libcups2 ca-certificates || \
  sudo apt-get install -y wget gnupg unzip xvfb fonts-liberation libnss3 libatk-bridge2.0-0 \
    libgtk-3-0 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 \
    libpangocairo-1.0-0 libcups2 ca-certificates
  wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y /tmp/chrome.deb || sudo dpkg -i /tmp/chrome.deb || true
  sudo apt-get install -y -f
fi
sudo apt-get install -y xvfb python3-pip python3-venv >/dev/null 2>&1 || true

if [ ! -d "$HOME/venv-imdb" ]; then
  python3 -m venv "$HOME/venv-imdb"
fi
# shellcheck disable=SC1091
source "$HOME/venv-imdb/bin/activate"
pip install -q --upgrade pip
pip install -q selenium webdriver-manager requests pandas

# --- pull inputs / resume ---
aws s3 sync "s3://${BUCKET}/${PREFIX}/code/" "$PIPE/" --exclude '*' --include '*.py' || true
aws s3 sync "s3://${BUCKET}/${PREFIX}/code/aws/" "$PIPE/aws/" || true
aws s3 sync "s3://${BUCKET}/${PREFIX}/input/" "$PIPE/data/" --exact-timestamps || true
# resume prior outputs if any
aws s3 sync "s3://${BUCKET}/${PREFIX}/results/" "$PIPE/data/" --exclude '*' \
  --include 'imdb_selenium_features_*.csv' \
  --include 'imdb_basics_ambiguous_selenium_*.csv' \
  --include 'imdb_ids.csv' \
  --exact-timestamps || true

if [ -z "${TMDB_API_KEY:-}" ] && [ -f "$PIPE/data/qa/tmdb_api_key" ]; then
  TMDB_API_KEY="$(tr -d ' \n\r' < "$PIPE/data/qa/tmdb_api_key")"
  export TMDB_API_KEY
fi
if [ "$MODE" != "posters" ] && [ -z "${TMDB_API_KEY:-}" ]; then
  echo "ERROR: TMDB_API_KEY missing (set env or stage input/qa/tmdb_api_key)"
  exit 1
fi

mkdir -p data/posters data/qa

# --- virtual display ---
if ! pgrep -f "Xvfb ${DISPLAY}" >/dev/null 2>&1; then
  echo "--- start Xvfb on $DISPLAY ---"
  Xvfb "$DISPLAY" -screen 0 1920x1080x24 -ac +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
  sleep 2
fi
export DISPLAY
echo "DISPLAY=$DISPLAY chrome=$(command -v google-chrome-stable || command -v google-chrome || echo missing)"

LIMIT_ARGS=()
if [ "${LIMIT}" != "0" ] && [ -n "${LIMIT}" ]; then
  LIMIT_ARGS=(--limit "$LIMIT")
fi

echo "--- run MODE=$MODE ---"
case "$MODE" in
  features)
    python3 -u enrich_imdb_selenium_features.py \
      --api-key "$TMDB_API_KEY" \
      --delay "$DELAY" \
      "${LIMIT_ARGS[@]}" \
      2>&1 | tee data/imdb_selenium_features_run.log
    ;;
  ambiguous)
    python3 -u resolve_imdb_ambiguous_selenium.py \
      --api-key "$TMDB_API_KEY" \
      --pause "${PAUSE:-1.2}" \
      "${LIMIT_ARGS[@]}" \
      2>&1 | tee data/imdb_basics_ambiguous_selenium_run.log
    ;;
  posters)
    # Selenium headed Chrome on Xvfb (same stack as MODE=features).
    # Playwright on AWS IPs was observed stuck at HTTP 202 forever.
    IDS_FILE="${POSTER_IDS_FILE:-data/qa/imdb_poster_browser_todo.csv}"
    if [ ! -f "$IDS_FILE" ]; then
      echo "ERROR: missing $IDS_FILE for MODE=posters"
      exit 1
    fi
    EXTRA=()
    if [ "${FORCE:-1}" = "1" ]; then EXTRA+=(--force); fi
    POSTER_ENGINE="${POSTER_ENGINE:-selenium}"
    if [ "$POSTER_ENGINE" = "playwright" ]; then
      pip install -q playwright requests
      python3 -m playwright install-deps chromium >/dev/null 2>&1 || true
      ENGINE_ARGS=(--engine playwright --channel chrome)
    else
      ENGINE_ARGS=(--engine selenium)
    fi
    # Incremental S3 progress — chain previously uploaded only at end
    (
      while true; do
        sleep "${PROGRESS_SYNC_SECS:-90}"
        for f in imdb_poster_hits.csv imdb_poster_miss.csv imdb_poster_browser_run.log imdb_poster_ids.csv; do
          [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/${PREFIX}/results/$f" --quiet || true
        done
        if [ -d data/posters ]; then
          aws s3 sync data/posters "s3://${BUCKET}/${PREFIX}/results/posters/" \
            --exclude '*' --include '*.jpg' --quiet || true
        fi
        printf '%s\n' "progress $(date -u +%Y%m%dT%H%M%SZ)" \
          | aws s3 cp - "s3://${BUCKET}/${PREFIX}/results/PROGRESS" --quiet || true
      done
    ) &
    PROGRESS_PID=$!
    trap 'kill "$PROGRESS_PID" 2>/dev/null || true' EXIT
    python3 -u pull_imdb_posters.py \
      --ids-file "$IDS_FILE" \
      --browser --headed \
      "${ENGINE_ARGS[@]}" \
      --challenge-wait "${CHALLENGE_WAIT:-8}" \
      --max-consecutive-blocks "${MAX_CONSECUTIVE_BLOCKS:-12}" \
      --delay "${DELAY:-1.2}" --jitter "${JITTER:-0.5}" \
      "${EXTRA[@]}" \
      "${LIMIT_ARGS[@]}" \
      2>&1 | tee data/imdb_poster_browser_run.log
    kill "$PROGRESS_PID" 2>/dev/null || true
    trap - EXIT
    ;;
  *)
    echo "ERROR: unknown MODE=$MODE (features|ambiguous|posters)"
    exit 1
    ;;
esac

echo "--- upload results ---"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
for f in \
  imdb_selenium_features_hits.csv \
  imdb_selenium_features_miss.csv \
  imdb_selenium_features_run.log \
  imdb_basics_ambiguous_selenium_hits.csv \
  imdb_basics_ambiguous_selenium_miss.csv \
  imdb_basics_ambiguous_selenium_run.log \
  imdb_poster_hits.csv \
  imdb_poster_miss.csv \
  imdb_poster_ids.csv \
  imdb_poster_browser_run.log \
  imdb_ids.csv
do
  if [ -f "data/$f" ]; then
    aws s3 cp "data/$f" "s3://${BUCKET}/${PREFIX}/results/$f"
    aws s3 cp "data/$f" "s3://${BUCKET}/${PREFIX}/results/archive/${ts}/$f" || true
  fi
done
# upload any newly downloaded posters for the todo set
if [ "$MODE" = "posters" ] && [ -d data/posters ]; then
  aws s3 sync data/posters "s3://${BUCKET}/${PREFIX}/results/posters/" \
    --exclude '*' --include '*.jpg' || true
fi
printf '%s\n' "IMDB_SELENIUM_DONE_${ts}" | aws s3 cp - "s3://${BUCKET}/${PREFIX}/results/IMDB_SELENIUM_DONE"
echo "=== imdb_selenium_chain LISTO $(date -u) ==="
