#!/usr/bin/env bash
# Start WFLike jobs dashboard poller (+ optional local HTTP for LAN/file fallback).
set -euo pipefail

# Avoid corporate/sandbox proxies breaking aws cli + S3 HTTPS
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  NO_PROXY no_proxy GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY \
  socks_proxy socks5_proxy 2>/dev/null || true

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PIPE="$ROOT/pipeline"
OUT="$PIPE/data/qa/jobs_dashboard"
LOG="$OUT/poller.log"
PIDF="$OUT/poller.pid"
HTTP_PIDF="$OUT/http.pid"
PORT="${JOBS_DASH_PORT:-8765}"
INTERVAL="${JOBS_DASH_INTERVAL:-45}"

mkdir -p "$OUT" "$OUT/cache" "$ROOT/site/jobs-dashboard"

is_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

if [[ -f "$PIDF" ]]; then
  old="$(tr -dc '0-9' <"$PIDF" || true)"
  if is_alive "$old"; then
    echo "Poller already running pid=$old"
    echo "  log: $LOG"
    echo "  status: $OUT/status.json"
    echo "  pages: https://juanpduque.github.io/what-fear-looks-like/jobs-dashboard/"
    echo "  public data: https://amaleli-website.s3.amazonaws.com/wflike-jobs-dashboard/status.json"
    if [[ -f "$HTTP_PIDF" ]]; then
      hpid="$(tr -dc '0-9' <"$HTTP_PIDF" || true)"
      if is_alive "$hpid"; then
        echo "  local UI: http://127.0.0.1:${PORT}/"
      fi
    fi
    exit 0
  fi
fi

cd "$PIPE"
: >>"$LOG"
nohup env PYTHONUNBUFFERED=1 python3 -u jobs_dashboard_poller.py --interval "$INTERVAL" \
  </dev/null >>"$LOG" 2>&1 &
echo $! >"$PIDF"
sleep 1
if ! is_alive "$(cat "$PIDF")"; then
  echo "ERROR: poller failed to stay up — see $LOG" >&2
  tail -30 "$LOG" >&2 || true
  exit 1
fi
echo "Started poller pid=$(cat "$PIDF") interval=${INTERVAL}s"
echo "  log: $LOG"

start_http() {
  cd "$ROOT/site/jobs-dashboard"
  nohup python3 -m http.server "$PORT" --bind 127.0.0.1 \
    </dev/null >>"$OUT/http.log" 2>&1 &
  echo $! >"$HTTP_PIDF"
  echo "Local UI: http://127.0.0.1:${PORT}/"
}

if command -v python3 >/dev/null 2>&1; then
  if [[ -f "$HTTP_PIDF" ]]; then
    hpid="$(tr -dc '0-9' <"$HTTP_PIDF" || true)"
    if is_alive "$hpid"; then
      echo "HTTP already on pid=$hpid port=$PORT"
    else
      start_http
    fi
  else
    start_http
  fi
fi

echo "GitHub Pages (after push): https://juanpduque.github.io/what-fear-looks-like/jobs-dashboard/"
echo "file:// fallback: file://$ROOT/site/jobs-dashboard/index.html"
echo "Docs: $ROOT/docs/JOBS_DASHBOARD.md"
echo "Stop: kill \$(cat $PIDF); kill \$(cat $HTTP_PIDF 2>/dev/null) 2>/dev/null || true"
# Tip: if launched from an agent sandbox that reaps children, run this script
# from Terminal.app / iTerm so the poller survives after the chat ends.
