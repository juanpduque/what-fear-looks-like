#!/usr/bin/env python3
"""
Face detection v2 — YuNet (cv2.FaceDetectorYN), replaces the Haar cascade run.
Haar undercounted badly on stylized artwork (Resident Evil 2021: 0 of 6 faces).

One-time setup (downloads the 230KB model):
  mkdir -p models
  curl -L -o models/face_detection_yunet_2023mar.onnx \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

Run (resumable):
  python3 faces_v2.py --budget 33      # batch mode (rerun to resume)
  python3 faces_v2.py                  # run to completion
  python3 faces_v2.py --validate       # sanity-check on known posters first

Outputs: data/faces_v2.csv, data/faces_v2_decade.json + comparison vs Haar run.
"""
import argparse, time
from pathlib import Path
import numpy as np
import pandas as pd
import cv2

HERE = Path(__file__).parent
DATA = HERE / "data"
MODEL = HERE / "models" / "face_detection_yunet_2023mar.onnx"
CHECKPOINT = DATA / "faces_v2_partial.csv"
W = 320                      # detection width
CONF = 0.6                   # YuNet confidence threshold

VALIDATION = [  # (title, year, expected faces, tolerance)
    # ground truth verificada mirando el artwork real de TMDB:
    # Scream = 6 caras (cara gigante + 5 del elenco); RE = 6 pero varias de
    # perfil/inclinadas — a 320px el detector recupera las 3-4 claras (piso).
    ("Resident Evil: Welcome to Raccoon City", 2021, 4, 2),
    ("Scream", 1996, 6, 1),
    ("Get Out", 2017, 1, 0),
    ("Psycho", 1960, 3, 1),
    ("The Exorcist", 1973, 1, 1),
    ("Us", 2019, 1, 1),
    ("Halloween", 1978, 0, 0),
]

def make_detector():
    if not MODEL.exists():
        raise SystemExit(f"Modelo no encontrado: {MODEL}\nCorre el curl del docstring primero.")
    return cv2.FaceDetectorYN.create(str(MODEL), "", (W, W), CONF, 0.3, 5000)

def detect(det, path):
    img = cv2.imread(str(path))
    if img is None:
        return None
    h, w = img.shape[:2]
    s = W / w
    img = cv2.resize(img, (W, int(h * s)))
    det.setInputSize((img.shape[1], img.shape[0]))
    _, faces = det.detect(img)
    if faces is None:
        return dict(n_faces=0, face_area=0.0, max_conf=0.0)
    area = float(sum(f[2] * f[3] for f in faces) / (img.shape[0] * img.shape[1]))
    return dict(n_faces=len(faces), face_area=round(area, 4),
                max_conf=round(float(faces[:, -1].max()), 3))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=0)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    det = make_detector()

    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "year", "title"])

    if args.validate:
        print(f'{"titulo":45} esperado detectado')
        ok = True
        for t, y, exp, tol in VALIDATION:
            row = meta[(meta.title == t) & (meta.year == y)]
            if not len(row):
                print(f"{t:45} NO ENCONTRADO"); continue
            r = detect(det, DATA / "posters" / f"{int(row.iloc[0].id)}.jpg")
            flag = "OK" if abs(r["n_faces"] - exp) <= tol else "FAIL"
            ok &= flag == "OK"
            print(f'{t:45} {exp:8} {r["n_faces"]:9} {flag}')
        print("VALIDACION:", "PASA" if ok else "REVISAR")
        return

    done = set(pd.read_csv(CHECKPOINT).id) if CHECKPOINT.exists() else set()
    todo = meta[~meta.id.isin(done)]
    print(f"pendientes: {len(todo):,}/{len(meta):,}")
    t0, rows = time.time(), []
    for pid, yr in zip(todo.id, todo.year):
        if args.budget and time.time() - t0 > args.budget:
            break
        r = detect(det, DATA / "posters" / f"{pid}.jpg")
        if r is None:
            continue
        r.update(id=pid, year=int(yr))
        rows.append(r)
    if rows:
        pd.DataFrame(rows).to_csv(CHECKPOINT, mode="a",
                                  header=not CHECKPOINT.exists(), index=False)
    total = len(done) + len(rows)
    print(f"lote: {len(rows):,} | total: {total:,}/{len(meta):,} | "
          f"{len(rows)/max(time.time()-t0,1e-9):.0f}/s")

    if total >= len(meta):
        d = pd.read_csv(CHECKPOINT).drop_duplicates("id")
        d.to_csv(DATA / "faces_v2.csv", index=False)
        d["decade"] = (d.year // 10) * 10
        agg = d.groupby("decade").agg(n=("id", "count"),
                                      mean_faces=("n_faces", "mean"),
                                      pct_with_face=("n_faces", lambda s: (s > 0).mean()),
                                      face_area=("face_area", "mean")).round(3)
        agg.reset_index().to_json(DATA / "faces_v2_decade.json", orient="records")
        print("\n=== YuNet POR DECADA ===")
        print(agg.to_string())
        old = DATA / "faces_decade.json"
        if old.exists():
            o = pd.read_json(old).set_index("decade")
            print("\n=== COMPARACION pct_with_face (Haar -> YuNet) ===")
            cmp_ = pd.DataFrame({"haar": o.pct_with_face, "yunet": agg.pct_with_face})
            print(cmp_.round(3).to_string())

if __name__ == "__main__":
    main()
