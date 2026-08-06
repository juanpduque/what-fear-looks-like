#!/usr/bin/env bash
# Local gallery: original vs homolog 1000×1500
#   bash pipeline/data/qa/homolog_compare/serve.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PORT="${PORT:-8765}"
echo "Homolog QA → http://127.0.0.1:${PORT}/qa/homolog_compare/"
echo "(Ctrl+C para parar)"
python3 -m http.server "$PORT" --bind 127.0.0.1
