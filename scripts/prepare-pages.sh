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

# Belt-and-suspenders: dev folders should not ship even if copied.
# The QA/review pages (comedy/ocr/drift/corpus-filter/label-qa) were removed
# from the repo; animation/tv-movie review pages remain gitignored local-only.
rm -rf \
  "$OUT/demos/poster-decompose/_shots" \
  "$OUT/demos/poster-decompose/captures" \
  "$OUT/demos/poster-decompose-cloud" \
  "$OUT/jobs-dashboard" \
  "$OUT/animation-review.html" \
  "$OUT/tv-movie-review.html" \
  2>/dev/null || true

echo "Pages artifact ready at $OUT ($(du -sh "$OUT" | cut -f1))"
