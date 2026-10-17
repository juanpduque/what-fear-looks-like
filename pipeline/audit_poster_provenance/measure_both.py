"""Same measures, two images per film: TMDB's poster (posters/{id}.jpg) vs the IMPAwards release-year poster."""

import json
import os
import sys
import time

import cv2
import numpy as np
import requests

sys.path.insert(0, ".")
import faces_v2 as F
import fear_pipeline as FP
import multi_analyze as MA

S = sys.argv[1]
OUT = S + "/sens.jsonl"
rows = {}
for l in open(S + "/impa_full.jsonl"):
    r = json.loads(l)
    if "dist" in r:
        rows[r["id"]] = r
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        done.add(json.loads(l)["id"])
det = F.make_detector()
rng = np.random.default_rng(0)
H = {"User-Agent": "what-fear-looks-like research (poster provenance check)"}


def measure(raw, path_for_faces):
    out = {}
    bgr0 = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    h, w = bgr0.shape[:2]
    s = MA.ANALYSIS_WIDTH / w
    bgr = cv2.resize(bgr0, (MA.ANALYSIS_WIDTH, int(h * s)))
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    for k in ("typography", "composition", "diagonal"):
        out.update(MA.REGISTRY[k](bgr, gray))
    a = FP.analyze_poster(raw, rng)
    out.update({k: a[k] for k in ("brightness", "dark_share", "saturation", "red_share") if k in a})
    img = cv2.resize(bgr0, (F.W, int(h * F.W / w)))
    ih, iw = img.shape[:2]
    det.setInputSize((iw, ih))
    _, f = det.detect(img)
    out["n_faces"] = 0 if f is None else len(f)
    out["face_area"] = 0.0 if f is None else float(sum(x[2] * x[3] for x in f) / (ih * iw))
    return out


todo = [r for i, r in rows.items() if i not in done]
print("por medir:", len(todo), flush=True)
for r in todo:
    rec = {"id": r["id"], "year": r["year"], "dist": r["dist"]}
    try:
        tm = open(f"data/posters/{r['id']}.jpg", "rb").read()
        cache = f"{S}/impa_img/{r['id']}.jpg"
        if os.path.exists(cache):
            im = open(cache, "rb").read()
        else:
            resp = requests.get(r["url"], headers=H, timeout=30)
            resp.raise_for_status()
            im = resp.content
            open(cache, "wb").write(im)
            time.sleep(1.0)
        rec["tmdb"] = measure(tm, None)
        rec["impa"] = measure(im, None)
    except Exception as e:
        rec["err"] = f"{type(e).__name__}: {e}"[:120]
    with open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")
print("FIN", flush=True)
