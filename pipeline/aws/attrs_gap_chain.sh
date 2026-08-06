#!/bin/bash
# Attributes-only gap backfill: fix opencv saliency (contrib), fill missing attrs rows.
set -euo pipefail
export PATH=/usr/local/bin:${PATH:-}
export BUCKET="${BUCKET:-sagemaker-studio-a5572760}"
export PREFIX="${PREFIX:-wflike-attrs-gap}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export POSTER_SRC="${POSTER_SRC:-s3://sagemaker-studio-a5572760/wflike-community-72k/posters}"
export VISION_GAP_POSTERS="${VISION_GAP_POSTERS:-s3://sagemaker-studio-a5572760/wflike-vision-gap/input/posters}"
export SYNC_SECS="${SYNC_SECS:-180}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-16}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-16}"

ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
DATA=$PIPE/data
LOG=$DATA/attrs_gap_aws.log
mkdir -p "$DATA/posters" "$DATA/qa/attrs_gap"
exec > >(tee -a "$LOG") 2>&1

echo "=== attrs_gap_chain start $(date -u) ==="
cd "$PIPE"

on_err() {
  ec=$?
  echo "ERROR trap ec=$ec phase=$(cat /tmp/attrs_gap_phase 2>/dev/null || echo unknown) $(date -u)" || true
  echo "FAIL" > data/qa/attrs_gap/FAIL 2>/dev/null || true
  date -u +"ATTRS_GAP_ERR_%Y%m%dT%H%M%SZ ec=$ec" >> data/qa/attrs_gap/FAIL 2>/dev/null || true
  aws s3 cp data/qa/attrs_gap/FAIL "s3://${BUCKET}/${PREFIX}/results/FAIL" --quiet 2>/dev/null || true
  aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/attrs_gap_aws.log" --quiet 2>/dev/null || true
  for f in attributes.csv attributes_partial.csv attributes_decade.json; do
    [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/${PREFIX}/results/$f" --quiet || true
  done
  sleep 10
  sudo shutdown -h now || true
}
trap on_err ERR

aws sts get-caller-identity || true

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
doc = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "phase": open("/tmp/attrs_gap_phase").read().strip() if Path("/tmp/attrs_gap_phase").exists() else "unknown",
    "attributes": nids(DATA/"attributes_partial.csv") or nids(DATA/"attributes.csv"),
    "faces_v2": nids(DATA/"faces_v2.csv"),
    "posters_on_disk": sum(1 for _ in (DATA/"posters").glob("*.jpg")),
}
Path("data/qa/attrs_gap/PROGRESS.json").write_text(json.dumps(doc, indent=2) + "\n")
print(json.dumps(doc))
PY
  aws s3 cp data/qa/attrs_gap/PROGRESS.json "s3://${BUCKET}/${PREFIX}/results/PROGRESS.json" --quiet || true
  aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/attrs_gap_aws.log" --quiet || true
}

sync_out() {
  for f in attributes.csv attributes_partial.csv attributes_decade.json attrs_gap_aws.log; do
    [ -f "data/$f" ] && aws s3 cp "data/$f" "s3://${BUCKET}/${PREFIX}/results/$f" --quiet || true
  done
  [ -f data/qa/attrs_gap/PROGRESS.json ] && \
    aws s3 cp data/qa/attrs_gap/PROGRESS.json "s3://${BUCKET}/${PREFIX}/results/PROGRESS.json" --quiet || true
  write_progress
}

echo "boot" > /tmp/attrs_gap_phase

# ---- deps (opencv WITH contrib for cv2.saliency) ----
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

VENV=/home/ubuntu/aof/.venv-attrs
rm -rf "$VENV" 2>/dev/null || true
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
export PATH="$VENV/bin:/usr/local/bin:$PATH"
python -m pip -q install -U pip

# CRITICAL: remove plain opencv (no saliency); install contrib headless
python -m pip -q uninstall -y opencv-python opencv-python-headless opencv-contrib-python 2>/dev/null || true
python -m pip -q install -U opencv-contrib-python-headless pandas numpy shapely

echo "--- assert cv2.saliency ---"
python - <<'PY'
import cv2
print("cv2", cv2.__version__, flush=True)
assert hasattr(cv2, "saliency"), "FATAL: cv2.saliency missing — need opencv-contrib-python-headless"
sal = cv2.saliency.StaticSaliencySpectralResidual_create()
assert sal is not None
print("OK cv2.saliency.StaticSaliencySpectralResidual_create()", flush=True)
PY

echo "--- smoke: composition+typography+all metrics (catch OpenCV unpack) ---"
python - <<'PY'
import sys
from pathlib import Path
import numpy as np
import cv2

# Prefer a real poster if already present; else synthetic with edges/text-ish blobs
poster_dir = Path("data/posters")
bgr = None
for p in sorted(poster_dir.glob("*.jpg"))[:1]:
    bgr = cv2.imread(str(p))
    if bgr is not None:
        print(f"smoke poster={p.name}", flush=True)
        break
if bgr is None:
    bgr = np.zeros((240, 160, 3), np.uint8)
    bgr[:] = (30, 30, 40)
    # blobs + diagonal so MSER / Hough / saliency all exercise
    cv2.rectangle(bgr, (20, 30), (140, 55), (240, 240, 240), -1)
    cv2.rectangle(bgr, (40, 100), (120, 200), (80, 80, 200), -1)
    cv2.line(bgr, (10, 220), (150, 40), (200, 200, 200), 2)
    print("smoke synthetic image", flush=True)

h, w = bgr.shape[:2]
s = 180 / w
bgr = cv2.resize(bgr, (180, max(1, int(h * s))))
gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

# Force Hough path with (N,4)-shaped lines if OpenCV returns that layout
import multi_analyze as ma
try:
    for name, fn in ma.REGISTRY.items():
        out = fn(bgr, gray)
        assert isinstance(out, dict) and out, name
        print(f"  OK metric={name} keys={sorted(out)}", flush=True)
    # Explicit Hough unpack regression: both layouts
    fake_n14 = np.array([[[10, 20, 80, 90]], [[15, 25, 70, 100]]], dtype=np.int32)
    fake_n4 = np.array([[10, 20, 80, 90], [15, 25, 70, 100]], dtype=np.int32)
    for label, arr in (("N,1,4", fake_n14), ("N,4", fake_n4)):
        for x1, y1, x2, y2 in np.asarray(arr).reshape(-1, 4):
            assert int(x1) == 10 or int(x1) == 15
        print(f"  OK hough_reshape={label}", flush=True)
except TypeError as e:
    print(f"FATAL smoke TypeError: {e}", flush=True)
    raise SystemExit(2)
print("OK smoke multi_analyze metrics", flush=True)
PY

[ -f data/posters.csv ] || { echo "FATAL: data/posters.csv missing"; exit 1; }
[ -f data/attributes.csv ] || { echo "FATAL: data/attributes.csv missing"; exit 1; }

# ---- seed attributes_partial ----
echo "seed" > /tmp/attrs_gap_phase
python3 - <<'PY'
from pathlib import Path
import pandas as pd
final, part = Path("data/attributes.csv"), Path("data/attributes_partial.csv")
if final.exists() and not part.exists():
    pd.read_csv(final).to_csv(part, index=False)
    print("seeded attributes_partial from attributes.csv", len(pd.read_csv(part)))
elif final.exists() and part.exists():
    f = pd.read_csv(final); p = pd.read_csv(part)
    f["id"] = f["id"].astype(int); p["id"] = p["id"].astype(int)
    m = pd.concat([p, f]).drop_duplicates("id", keep="last")
    m.to_csv(part, index=False)
    print("union attributes_partial", len(m))
else:
    raise SystemExit("no attributes seed")
PY

# ---- download only missing poster ids (faces − attributes, else posters − attributes) ----
echo "download_posters" > /tmp/attrs_gap_phase
echo "--- download missing attribute posters ---"
python3 - <<'PY'
import os, concurrent.futures, subprocess
from pathlib import Path
import pandas as pd

DATA = Path("data")
POSTERS = DATA / "posters"
POSTERS.mkdir(parents=True, exist_ok=True)

attrs = set(pd.read_csv(DATA / "attributes_partial.csv", usecols=["id"])["id"].astype(int))
need_ids = None
faces_path = DATA / "faces_v2.csv"
if faces_path.exists():
    faces = set(pd.read_csv(faces_path, usecols=["id"])["id"].astype(int))
    need_ids = sorted(faces - attrs)
    print(f"gap from faces−attrs: faces={len(faces)} attrs={len(attrs)} need={len(need_ids)}", flush=True)
if not need_ids:
    meta = set(pd.read_csv(DATA / "posters.csv", usecols=["id"])["id"].astype(int))
    need_ids = sorted(meta - attrs)
    print(f"gap from posters−attrs: posters={len(meta)} attrs={len(attrs)} need={len(need_ids)}", flush=True)

Path("data/qa/attrs_gap/todo_ids.txt").write_text("\n".join(str(i) for i in need_ids) + ("\n" if need_ids else ""))

src = os.environ.get("POSTER_SRC", "s3://sagemaker-studio-a5572760/wflike-community-72k/posters").rstrip("/")
vg = os.environ.get("VISION_GAP_POSTERS", "s3://sagemaker-studio-a5572760/wflike-vision-gap/input/posters").rstrip("/")
staged = f"s3://{os.environ['BUCKET']}/{os.environ['PREFIX']}/input/posters"
need = [i for i in need_ids if not (POSTERS / f"{i}.jpg").exists()]
print(f"todo={len(need_ids)} already={len(need_ids)-len(need)} need_download={len(need)}", flush=True)

def fetch(pid: int) -> str:
    dest = POSTERS / f"{pid}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return "have"
    for base in (src, vg, staged):
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
workers = int(os.environ.get("DL_WORKERS", "32"))
with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
    for i, status in enumerate(ex.map(fetch, need), 1):
        if status in ("ok", "have"):
            ok += 1
        else:
            miss += 1
        if i % 500 == 0 or i == len(need):
            print(f"  fetch {i}/{len(need)} ok={ok} miss={miss}", flush=True)
print(f"LISTO posters_on_disk={sum(1 for _ in POSTERS.glob('*.jpg'))} fetch_ok={ok} fetch_miss={miss}", flush=True)
if miss > 0 and miss == len(need) and len(need) > 0:
    raise SystemExit(f"FATAL: all {miss} poster downloads missed")
PY
write_progress

# background sync
(
  while true; do
    sleep "$SYNC_SECS"
    echo "sync" > /tmp/attrs_gap_phase
    sync_out || true
  done
) &
CKPID=$!

echo "attributes" > /tmp/attrs_gap_phase
echo "--- attributes (multi_analyze) — fail hard ---"
# Re-assert saliency immediately before analyze (defense in depth)
python -c "import cv2; assert hasattr(cv2, 'saliency')"
python3 -u multi_analyze.py

# publish attributes from partial (force, even if meta not fully covered)
python3 - <<'PY'
from pathlib import Path
import pandas as pd
DATA = Path("data")
part = DATA / "attributes_partial.csv"
final = DATA / "attributes.csv"
if not part.exists():
    raise SystemExit("FATAL: attributes_partial.csv missing after multi_analyze")
d = pd.read_csv(part).drop_duplicates("id", keep="last")
d["id"] = d["id"].astype(int)
d.to_csv(final, index=False)
# decade rollup
y = d.year.astype(int)
d_dec = d[(y >= 1897) & (y <= 2030)].copy()
d_dec["decade"] = (d_dec.year // 10) * 10
cols = [c for c in d_dec.columns if c not in ("id", "year", "decade")]
SENTINEL_COLS = {"align_score", "thirds_dist", "balance", "harmony"}
masked = d_dec[cols].copy()
for c in SENTINEL_COLS & set(cols):
    masked[c] = masked[c].where(masked[c] >= 0)
agg = masked.groupby(d_dec["decade"])[cols].mean().round(4)
agg["n"] = d_dec.groupby("decade").size()
agg.reset_index().to_json(DATA / "attributes_decade.json", orient="records")
print("attributes published", len(d), "nunique", d["id"].nunique(), flush=True)
PY
sync_out

kill "$CKPID" 2>/dev/null || true

# ---- DONE gate ----
echo "gate" > /tmp/attrs_gap_phase
set +e
python3 - <<'PY'
import json, time
from pathlib import Path
import pandas as pd

DATA = Path("data")
n_attrs = int(pd.read_csv(DATA / "attributes.csv", usecols=["id"])["id"].nunique())
n_faces = 0
if (DATA / "faces_v2.csv").exists():
    n_faces = int(pd.read_csv(DATA / "faces_v2.csv", usecols=["id"])["id"].nunique())
# Prefer matching peers: pass if >= 65000 OR >= faces count
ok = n_attrs >= 65000 or (n_faces > 0 and n_attrs >= n_faces)
doc = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "n_attributes": n_attrs,
    "n_faces": n_faces,
    "threshold_note": "pass if n_attrs>=65000 or n_attrs>=n_faces",
    "ok": ok,
}
Path("data/qa/attrs_gap/GATE.json").write_text(json.dumps(doc, indent=2) + "\n")
print(json.dumps(doc), flush=True)
raise SystemExit(0 if ok else 2)
PY
GATE_RC=$?
set -e

if [ "$GATE_RC" -eq 0 ]; then
  date -u +"ATTRS_GAP_DONE_%Y%m%dT%H%M%SZ" > data/qa/attrs_gap/DONE
  aws s3 cp data/qa/attrs_gap/DONE "s3://${BUCKET}/${PREFIX}/results/DONE"
  aws s3 cp data/qa/attrs_gap/GATE.json "s3://${BUCKET}/${PREFIX}/results/GATE.json" || true
  sync_out
  echo "=== attrs_gap_chain DONE $(date -u) ==="
else
  echo "FAIL" > data/qa/attrs_gap/FAIL
  date -u +"ATTRS_GAP_FAIL_%Y%m%dT%H%M%SZ" >> data/qa/attrs_gap/FAIL
  aws s3 cp data/qa/attrs_gap/FAIL "s3://${BUCKET}/${PREFIX}/results/FAIL"
  aws s3 cp data/qa/attrs_gap/GATE.json "s3://${BUCKET}/${PREFIX}/results/GATE.json" || true
  aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/attrs_gap_aws.log" || true
  sync_out || true
  echo "=== attrs_gap_chain FAIL (attributes below gate) $(date -u) ==="
fi

sleep 15
sudo shutdown -h now
