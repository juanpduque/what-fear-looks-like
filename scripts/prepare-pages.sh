#!/usr/bin/env bash
# Build site/ with Vite for GitHub Pages — exclude dev artifacts (_shots, QA pages).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE="$ROOT/site"
OUT="$ROOT/_site_pages"

rm -rf "$OUT"

echo "Building site with Vite…"
(cd "$SITE" && npm ci && npm run build)

cp -a "$SITE/dist/." "$OUT/"

# Belt-and-suspenders: dev folders should not ship even if copied
rm -rf \
  "$OUT/demos/poster-decompose/_shots" \
  "$OUT/demos/poster-decompose/captures" \
  "$OUT/demos/poster-decompose-cloud" \
  "$OUT/jobs-dashboard" \
  "$OUT/animation-review.html" \
  "$OUT/comedy-review.html" \
  "$OUT/corpus-filter-qa.html" \
  "$OUT/label-qa-medium.html" \
  "$OUT/label-qa-typography.html" \
  "$OUT/ocr-title-review.html" \
  "$OUT/poster-drift-review.html" \
  "$OUT/tv-movie-review.html" \
  "$OUT/LABEL_QA_MEDIUM.md" \
  "$OUT/data/weapon_boxes.js" \
  2>/dev/null || true

echo "Pages artifact ready at $OUT ($(du -sh "$OUT" | cut -f1))"
