#!/bin/bash
# Stage community-72k AWS pipeline (enumerate → S3 posters → Rekognition).
# Does NOT upload local posters. Only uploads code, skip-id lists, TMDB key.
#
# Usage:
#   export AWS_PROFILE=sandbox
#   source ~/.zshrc   # TMDB_API_KEY
#   bash pipeline/aws/stage_community_72k.sh
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy \
  no_proxy NO_PROXY || true

BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${PREFIX:-wflike-community-72k}"

PIPE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PIPE"
mkdir -p data/qa/community_72k

DRY=0
for a in "$@"; do
  [ "$a" = "--dry-run" ] && DRY=1
done

echo "=== stage_community_72k → s3://${BUCKET}/${PREFIX}/ ==="

need=(
  tmdb_enumerate_horror.py
  community_72k_aws_worker.py
  aws/community_72k_chain.sh
  aws/community_72k_userdata.sh
)
for f in "${need[@]}"; do
  if [ ! -f "$f" ]; then
    echo "missing $f"; exit 1
  fi
done

if [ -z "${TMDB_API_KEY:-}" ]; then
  echo "ERROR: TMDB_API_KEY not set (needed for EC2 enumerate+download)"
  exit 1
fi

STAGE=data/qa/community_72k/_stage
rm -rf "$STAGE"
mkdir -p "$STAGE/code/aws" "$STAGE/input/qa" "$STAGE/results"

cp -f tmdb_enumerate_horror.py "$STAGE/code/"
cp -f community_72k_aws_worker.py "$STAGE/code/"
cp -f aws/community_72k_chain.sh "$STAGE/code/aws/"
cp -f aws/community_72k_userdata.sh "$STAGE/code/aws/"

# Skip lists: ids already processed locally — avoid double-billing
python3 <<'PY'
import csv
from pathlib import Path

data = Path("data")
qa = Path("data/qa/community_72k/_stage/input/qa")
qa.mkdir(parents=True, exist_ok=True)

def ids_from_csv(path, id_col="id"):
    out = set()
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out.add(int(float(r[id_col])))
            except Exception:
                pass
    return out

labels = set()
labels |= ids_from_csv(data / "rekognition.csv")
labels |= ids_from_csv(data / "qa" / "rekognition_community_enrich.csv")
(qa / "skip_labels_ids.txt").write_text("\n".join(str(i) for i in sorted(labels)) + ("\n" if labels else ""), encoding="utf-8")

text = set()
text |= ids_from_csv(data / "poster_ocr_rek_text.csv")
text |= ids_from_csv(data / "poster_ocr_rek_text_alllang.csv")
(qa / "skip_detecttext_ids.txt").write_text("\n".join(str(i) for i in sorted(text)) + ("\n" if text else ""), encoding="utf-8")

print(f"skip_labels={len(labels):,} skip_detecttext={len(text):,}")
meta = {
    "skip_labels": len(labels),
    "skip_detecttext": len(text),
    "note": "EC2 skips these for Labels/DetectText; still enumerates full TMDB set and downloads missing posters to S3 only",
}
import json
(qa / "skip_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
# also copy to status helper path
Path("data/qa/community_72k").mkdir(parents=True, exist_ok=True)
(Path("data/qa/community_72k") / "skip_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
PY

printf '%s' "$TMDB_API_KEY" > "$STAGE/input/qa/tmdb_api_key"
chmod 600 "$STAGE/input/qa/tmdb_api_key"

cat > "$STAGE/ENV" <<EOF
export BUCKET=${BUCKET}
export PREFIX=${PREFIX}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
export DOWNLOAD_WORKERS=${DOWNLOAD_WORKERS:-24}
export REK_WORKERS=${REK_WORKERS:-10}
export MIN_INTERVAL=${MIN_INTERVAL:-0.04}
export SAVE_EVERY=${SAVE_EVERY:-25}
export SYNC_SECS=${SYNC_SECS:-120}
EOF

echo "staged files:"
find "$STAGE" -type f | sed "s|^$STAGE/|  |" | grep -v tmdb_api_key
echo "  input/qa/tmdb_api_key (secret, not listed)"

if [ "$DRY" = "1" ]; then
  echo "DRY RUN — not uploading"
  exit 0
fi

echo "--- upload ---"
aws s3 sync "$STAGE/code/" "s3://${BUCKET}/${PREFIX}/code/"
aws s3 sync "$STAGE/input/" "s3://${BUCKET}/${PREFIX}/input/"
aws s3 cp "$STAGE/ENV" "s3://${BUCKET}/${PREFIX}/ENV"
# wipe local staged secret copy after upload
rm -f "$STAGE/input/qa/tmdb_api_key"
echo "LISTO stage → s3://${BUCKET}/${PREFIX}/"
echo "Siguiente: bash pipeline/aws/launch_community_72k.sh"
