#!/bin/bash
# Vision gap backfill: faces_v2 · attributes · clip_embed · census · typography · medium · segmentation
# Seeds from essay masters (~37.8k), processes posters_extended TODO (~27k), uploads to S3, halts.
set -euo pipefail
export PATH=/usr/local/bin:${PATH:-}
export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-vision-gap}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export POSTER_SRC="${POSTER_SRC:-s3://sagemaker-studio-a5572760/wflike-community-72k/posters}"
export SYNC_SECS="${SYNC_SECS:-180}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-16}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-16}"
export TORCH_NUM_THREADS="${TORCH_NUM_THREADS:-16}"

ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
DATA=$PIPE/data
LOG=$DATA/vision_gap_aws.log
mkdir -p "$DATA/posters" "$DATA/qa/vision_gap" "$PIPE/models"
exec > >(tee -a "$LOG") 2>&1

echo "=== vision_gap_chain start $(date -u) ==="
cd "$PIPE"
aws sts get-caller-identity || true
# Torch probe runs AFTER deps install (overnight fail: ModuleNotFoundError torch).

write_progress() {
  python3 - <<'PY'
import json, time
from pathlib import Path
DATA = Path("data")
def nids(p):
    try:
        import pandas as pd
        return int(pd.read_csv(p, usecols=["id"])["id"].nunique())
    except Exception:
        return 0
def nemb(p):
    try:
        import numpy as np
        return int(len(np.load(p)["ids"]))
    except Exception:
        return 0
doc = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "phase": open("/tmp/vision_gap_phase").read().strip() if Path("/tmp/vision_gap_phase").exists() else "unknown",
    "faces_v2": nids(DATA/"faces_v2_partial.csv") or nids(DATA/"faces_v2.csv"),
    "attributes": nids(DATA/"attributes_partial.csv") or nids(DATA/"attributes.csv"),
    "segmentation": nids(DATA/"segmentation_partial.csv") or nids(DATA/"segmentation.csv"),
    "medium": nids(DATA/"medium.csv"),
    "census": nids(DATA/"census.csv"),
    "typography": nids(DATA/"typography.csv"),
    "clip_embeddings": nemb(DATA/"clip_embeddings_partial.npz") or nemb(DATA/"clip_embeddings.npz"),
    "posters_on_disk": sum(1 for _ in (DATA/"posters").glob("*.jpg")),
}
Path("data/qa/vision_gap/PROGRESS.json").write_text(json.dumps(doc, indent=2) + "\n")
print(json.dumps(doc))
PY
  aws s3 cp data/qa/vision_gap/PROGRESS.json "s3://${BUCKET}/${PREFIX}/results/PROGRESS.json" --quiet || true
  aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/vision_gap_aws.log" --quiet || true
}

sync_out() {
  for f in \
    faces_v2.csv faces_v2_partial.csv faces_v2_decade.json \
    attributes.csv attributes_partial.csv attributes_decade.json \
    clip_embeddings.npz clip_embeddings_partial.npz \
    census.csv census_decade.json \
    typography.csv typography_decade.json \
    medium.csv medium_yearly.json \
    segmentation.csv segmentation_partial.csv segmentation_decade.json \
    posters.csv vision_gap_aws.log
  do
    [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/${PREFIX}/results/$f" --quiet || true
  done
  write_progress
}

echo "boot" > /tmp/vision_gap_phase

# ---- deps ----
echo "--- apt/pip (retry + regional mirror on 503) ---"
for n in 1 2 3 4 5 6 7 8; do
  if sudo apt-get update -y && sudo apt-get install -y python3-pip python3-venv libgl1 libglib2.0-0 curl ca-certificates; then
    break
  fi
  echo "apt failed attempt $n — switch to us-east-1 ec2 mirror"
  sudo sed -i.bak \
    -e 's|http://[a-zA-Z0-9.-]*archive.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
    -e 's|https://[a-zA-Z0-9.-]*archive.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
    -e 's|http://security.ubuntu.com/ubuntu|http://us-east-1.ec2.archive.ubuntu.com/ubuntu|g' \
    /etc/apt/sources.list || true
  sleep $((n * 15))
done
VENV=/home/ubuntu/aof/.venv-vision
rm -rf "$VENV" 2>/dev/null || true
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
export PATH="$VENV/bin:/usr/local/bin:$PATH"
python -m pip -q install -U pip
python -m pip -q install -U pandas numpy pillow opencv-python-headless shapely scikit-learn
# Torch: prefer CUDA wheel if GPU present, else CPU
if python -c "import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
  echo "torch already has cuda"
else
  if command -v nvidia-smi >/dev/null 2>&1; then
    python -m pip -q install -U torch torchvision --index-url https://download.pytorch.org/whl/cu124 || \
      python -m pip -q install -U torch torchvision
  else
    python -m pip -q install -U torch torchvision --index-url https://download.pytorch.org/whl/cpu
  fi
fi
python -m pip -q install -U open_clip_torch transformers
python - <<'PY'
import torch
print("cuda", torch.cuda.is_available(), "torch", torch.__version__)
PY

# ---- YuNet ----
mkdir -p models
if [ ! -f models/face_detection_yunet_2023mar.onnx ]; then
  curl -fsSL -o models/face_detection_yunet_2023mar.onnx \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
fi

# ---- input masters / meta already staged under data/ ----
[ -f data/posters.csv ] || { echo "FATAL: data/posters.csv missing"; exit 1; }
[ -f data/qa/vision_gap/todo_ids.txt ] || { echo "FATAL: todo_ids missing"; exit 1; }

# ---- download posters for TODO ----
echo "download_posters" > /tmp/vision_gap_phase
echo "--- download TODO posters ---"
python3 - <<'PY'
import os, concurrent.futures, subprocess
from pathlib import Path

DATA = Path("data")
POSTERS = DATA / "posters"
POSTERS.mkdir(parents=True, exist_ok=True)
todo = [int(x) for x in (DATA/"qa/vision_gap/todo_ids.txt").read_text().split() if x.strip()]
src = os.environ.get("POSTER_SRC", "s3://sagemaker-studio-a5572760/wflike-community-72k/posters").rstrip("/")
staged = f"s3://{os.environ['BUCKET']}/{os.environ['PREFIX']}/input/posters"
need = [i for i in todo if not (POSTERS / f"{i}.jpg").exists()]
print(f"todo={len(todo)} already={len(todo)-len(need)} need={len(need)}", flush=True)

def fetch(pid: int) -> str:
    dest = POSTERS / f"{pid}.jpg"
    if dest.exists():
        return "have"
    # prefer community bucket, then staged must_upload
    for base in (src, staged):
        uri = f"{base}/{pid}.jpg"
        r = subprocess.run(
            ["aws", "s3", "cp", uri, str(dest), "--quiet"],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return "ok"
        dest.unlink(missing_ok=True)
    return "miss"

ok = miss = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=int(os.environ.get("DL_WORKERS", "32"))) as ex:
    for i, status in enumerate(ex.map(fetch, need), 1):
        if status in ("ok", "have"):
            ok += 1
        else:
            miss += 1
        if i % 500 == 0 or i == len(need):
            print(f"  fetch {i}/{len(need)} ok={ok} miss={miss}", flush=True)
print(f"LISTO posters_on_disk={sum(1 for _ in POSTERS.glob('*.jpg'))} fetch_ok={ok} fetch_miss={miss}", flush=True)
PY
write_progress

# background sync
(
  while true; do
    sleep "$SYNC_SECS"
    echo "sync" > /tmp/vision_gap_phase
    sync_out || true
  done
) &
CKPID=$!

seed_partial() {
  # $1 final csv, $2 partial csv
  python3 - <<PY
from pathlib import Path
import pandas as pd
final, part = Path("data/$1"), Path("data/$2")
if final.exists() and not part.exists():
    pd.read_csv(final).to_csv(part, index=False)
    print("seeded $2 from $1", len(pd.read_csv(part)))
elif final.exists() and part.exists():
    f=pd.read_csv(final); p=pd.read_csv(part)
    f["id"]=f["id"].astype(int); p["id"]=p["id"].astype(int)
    m=pd.concat([p,f]).drop_duplicates("id", keep="last")
    m.to_csv(part, index=False)
    print("union $2", len(m))
PY
}

echo "faces_v2" > /tmp/vision_gap_phase
echo "--- faces_v2 ---"
seed_partial faces_v2.csv faces_v2_partial.csv
python3 -u faces_v2.py || true
# force publish from partial even if meta not fully covered
python3 - <<'PY'
from pathlib import Path
import pandas as pd
import faces_v2
DATA=Path("data")
part=DATA/"faces_v2_partial.csv"
if part.exists():
    d=pd.read_csv(part).drop_duplicates("id")
    faces_v2.finalize(d)
    print("faces_v2 forced finalize", len(d))
PY
sync_out

echo "attributes" > /tmp/vision_gap_phase
echo "--- attributes (multi_analyze) ---"
seed_partial attributes.csv attributes_partial.csv
python3 -u multi_analyze.py || true
# publish attributes from partial
python3 - <<'PY'
from pathlib import Path
import pandas as pd, json
DATA=Path("data")
part=DATA/"attributes_partial.csv"
final=DATA/"attributes.csv"
if part.exists():
    d=pd.read_csv(part).drop_duplicates("id", keep="last")
    d.to_csv(final, index=False)
    print("attributes published", len(d))
PY
sync_out

echo "clip_embed" > /tmp/vision_gap_phase
echo "--- clip_embed ---"
python3 -u clip_embed.py
sync_out

echo "census_typography_medium" > /tmp/vision_gap_phase
echo "--- census / typography / medium ---"
python3 -u clip_census.py
python3 -u clip_typography_axis.py
python3 -u clip_medium.py
sync_out

echo "segmentation" > /tmp/vision_gap_phase
echo "--- segmentation ---"
seed_partial segmentation.csv segmentation_partial.csv
python3 -u segmentation.py || true
python3 - <<'PY'
from pathlib import Path
import pandas as pd
# ensure final csv exists even if finalize skipped
DATA=Path("data")
part=DATA/"segmentation_partial.csv"
final=DATA/"segmentation.csv"
if part.exists():
    d=pd.read_csv(part).drop_duplicates("id", keep="last")
    d.to_csv(final, index=False)
    print("segmentation published", len(d))
PY
sync_out

kill "$CKPID" 2>/dev/null || true
echo "done" > /tmp/vision_gap_phase
date -u +"VISION_GAP_DONE_%Y%m%dT%H%M%SZ" > data/qa/vision_gap/DONE
aws s3 cp data/qa/vision_gap/DONE "s3://${BUCKET}/${PREFIX}/results/DONE"
sync_out
echo "=== vision_gap_chain done $(date -u) ==="
sleep 15
sudo shutdown -h now
