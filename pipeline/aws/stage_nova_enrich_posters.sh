#!/usr/bin/env bash
# Stage pending posters + state for cloud Nova enrich.
# Usage:
#   export AWS_PROFILE=sandbox AWS_DEFAULT_REGION=us-west-2
#   bash pipeline/aws/stage_nova_enrich_posters.sh
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-sandbox}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy || true

BUCKET="${NOVA_ENRICH_S3_BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${NOVA_ENRICH_S3_PREFIX:-wflike-nova-enrich/cloud}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_ENRICH="$PIPE/data/qa/nova_enrich"
POSTERS="$PIPE/data/posters"
STAGE_DIR="$LOCAL_ENRICH/cloud_stage"
DEST="s3://${BUCKET}/${PREFIX}"

mkdir -p "$STAGE_DIR"

echo "=== stage nova enrich → ${DEST} ==="

python3 - <<PY
import csv, json
from pathlib import Path

pipe = Path(r"""$PIPE""")
posters_csv = pipe / "data" / "posters.csv"
enrich_csv = pipe / "data" / "qa" / "nova_enrich" / "nova_enrich.csv"
posters_dir = pipe / "data" / "posters"
stage = pipe / "data" / "qa" / "nova_enrich" / "cloud_stage"
stage.mkdir(parents=True, exist_ok=True)

done = set()
if enrich_csv.exists():
    with enrich_csv.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if str(r.get("status") or "") == "ok":
                try:
                    done.add(int(r["id"]))
                except (TypeError, ValueError):
                    pass

meta = {}
if posters_csv.exists():
    with posters_csv.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (TypeError, ValueError):
                continue
            meta[str(pid)] = {
                "id": pid,
                "title": r.get("title") or "",
                "year": r.get("year") or "",
            }

# Full local JPG set (essay + community), not only posters.csv
todo = []
for p in sorted(posters_dir.glob("*.jpg")) + sorted(posters_dir.glob("*.png")):
    try:
        pid = int(p.stem)
    except ValueError:
        continue
    if pid in done:
        continue
    todo.append(pid)
    if str(pid) not in meta:
        meta[str(pid)] = {"id": pid, "title": "", "year": ""}

todo = sorted(set(todo))
(stage / "todo_ids.json").write_text(json.dumps(todo), encoding="utf-8")
(stage / "posters_meta.json").write_text(
    json.dumps({"by_id": meta}, ensure_ascii=False), encoding="utf-8"
)
(stage / "manifest.txt").write_text(
    "\n".join(str(i) for i in todo) + ("\n" if todo else ""), encoding="utf-8"
)
print(f"done_ok={len(done)} todo={len(todo)} local_jpg_png={len(list(posters_dir.glob('*.jpg')))+len(list(posters_dir.glob('*.png')))}")
print(f"wrote {stage/'todo_ids.json'}")
PY

echo "--- upload state ---"
aws s3 cp "$LOCAL_ENRICH/nova_enrich.csv" "${DEST}/nova_enrich.csv" --only-show-errors
aws s3 cp "$PIPE/data/posters.csv" "${DEST}/posters.csv" --only-show-errors
aws s3 cp "$STAGE_DIR/todo_ids.json" "${DEST}/todo_ids.json" --only-show-errors
aws s3 cp "$STAGE_DIR/posters_meta.json" "${DEST}/posters_meta.json" --only-show-errors
aws s3 cp "$STAGE_DIR/manifest.txt" "${DEST}/manifest.txt" --only-show-errors
# Existing OK ids are already excluded from todo_ids.json — skip syncing local json/
if [[ "${STAGE_SYNC_JSON:-0}" == "1" && -d "$LOCAL_ENRICH/json" ]]; then
  echo "--- sync existing json (done) ---"
  aws s3 sync "$LOCAL_ENRICH/json" "${DEST}/json" --only-show-errors
fi

echo "--- upload pending posters (symlink farm + sync) ---"
LINK_DIR="$STAGE_DIR/poster_links"
rm -rf "$LINK_DIR"
mkdir -p "$LINK_DIR"
python3 - <<PY
import json
from pathlib import Path
pipe = Path(r"""$PIPE""")
todo = json.loads((pipe / "data/qa/nova_enrich/cloud_stage/todo_ids.json").read_text())
posters = pipe / "data" / "posters"
link_dir = pipe / "data/qa/nova_enrich/cloud_stage/poster_links"
link_dir.mkdir(parents=True, exist_ok=True)
n = linked = missing = png = 0
for pid in todo:
    n += 1
    pid = int(pid)
    jpg = posters / f"{pid}.jpg"
    png_p = posters / f"{pid}.png"
    dest = link_dir / f"{pid}.jpg"
    if dest.exists() or dest.is_symlink():
        linked += 1
        continue
    if jpg.exists():
        dest.symlink_to(jpg.resolve())
        linked += 1
    elif png_p.exists():
        from PIL import Image
        im = Image.open(png_p).convert("RGB")
        im.save(dest, format="JPEG", quality=90)
        png += 1
        linked += 1
    else:
        missing += 1
    if n % 5000 == 0:
        print(f"  links {n}/{len(todo)}", flush=True)
print(f"links ready linked={linked} png_converted={png} missing={missing}")
PY
aws s3 sync "$LINK_DIR" "${DEST}/posters" --only-show-errors --size-only
echo "poster sync finished"
# count remote
aws s3 ls "${DEST}/posters/" --recursive | wc -l | awk '{print "remote_poster_objects",$1}'

echo "=== stage complete → ${DEST} ==="
aws s3 ls "${DEST}/" | head -20
