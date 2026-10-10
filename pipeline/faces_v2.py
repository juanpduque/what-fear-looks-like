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
  python3 faces_v2.py --rebox          # full re-detect + face_boxes for lookup overlay
  python3 faces_v2.py --validate       # sanity-check on known posters first

Outputs: data/faces_v2.csv (incl. face_boxes), data/faces_v2_decade.json
"""
import argparse
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "data"
MODEL = HERE / "models" / "face_detection_yunet_2023mar.onnx"
CHECKPOINT = DATA / "faces_v2_partial.csv"
W = 320                      # detection width
CONF = 0.6                   # YuNet confidence threshold

VALIDATION = [  # (title, year, expected faces, tolerance)
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
        raise SystemExit(
            f"Modelo no encontrado: {MODEL}\nCorre el curl del docstring primero."
        )
    return cv2.FaceDetectorYN.create(str(MODEL), "", (W, W), CONF, 0.3, 5000)


_WORKER_DET = None


def _pool_init():
    global _WORKER_DET
    _WORKER_DET = make_detector()


def _detect_one(args):
    pid, path, yr = args
    r = detect(_WORKER_DET, path)
    if r is None:
        return None
    r.update(id=int(pid), year=int(yr))
    return r


def detect(det, path):
    img = cv2.imread(str(path))
    if img is None:
        return None
    h, w = img.shape[:2]
    s = W / w
    img = cv2.resize(img, (W, int(h * s)))
    ih, iw = img.shape[:2]
    det.setInputSize((iw, ih))
    _, faces = det.detect(img)
    if faces is None:
        return dict(n_faces=0, face_area=0.0, max_conf=0.0, face_boxes="")
    area = float(sum(f[2] * f[3] for f in faces) / (ih * iw))
    boxes = []
    for f in faces:
        boxes.append([
            round(float(f[0]) / iw, 4),
            round(float(f[1]) / ih, 4),
            round(float(f[2]) / iw, 4),
            round(float(f[3]) / ih, 4),
        ])
    boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
    boxes_s = "|".join(f"{x},{y},{bw},{bh}" for x, y, bw, bh in boxes)
    return dict(
        n_faces=len(faces),
        face_area=round(area, 4),
        max_conf=round(float(faces[:, -1].max()), 3),
        face_boxes=boxes_s,
    )


def finalize(d: pd.DataFrame, out_csv: Path | None = None, out_decade: Path | None = None):
    out_csv = out_csv or (DATA / "faces_v2.csv")
    out_decade = out_decade or (DATA / "faces_v2_decade.json")
    d = d.drop_duplicates("id")
    d.to_csv(out_csv, index=False)
    y = d.year.astype(int)
    d_dec = d[(y >= 1897) & (y <= 2030)].copy()
    d_dec["decade"] = (d_dec.year // 10) * 10
    agg = d_dec.groupby("decade").agg(
        n=("id", "count"),
        mean_faces=("n_faces", "mean"),
        pct_with_face=("n_faces", lambda s: (s > 0).mean()),
        face_area=("face_area", "mean"),
    ).round(3)
    agg.reset_index().to_json(out_decade, orient="records")
    print("\n=== YuNet POR DECADA ===")
    print(agg.to_string())
    with_boxes = (d["face_boxes"].fillna("").astype(str) != "").sum()
    print(f"con face_boxes: {with_boxes:,}/{len(d):,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=0)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument(
        "--rebox",
        action="store_true",
        help="Ignore checkpoint; re-detect all and write face_boxes",
    )
    ap.add_argument("--meta-csv", default="", help="override id source (default posters.csv)")
    ap.add_argument("--out", default="", help="override output csv (keeps corpora separate)")
    ap.add_argument("--checkpoint", default="", help="override checkpoint path")
    ap.add_argument("--workers", type=int, default=6, help="parallel processes (CPU-bound, ~1 per core minus headroom)")
    args = ap.parse_args()

    global CHECKPOINT
    out_csv = Path(args.out) if args.out else None
    out_decade = (out_csv.parent / (out_csv.stem + "_decade.json")) if out_csv else None
    if args.checkpoint:
        CHECKPOINT = Path(args.checkpoint)

    det = make_detector()

    meta = pd.read_csv(Path(args.meta_csv) if args.meta_csv else (DATA / "posters.csv"), usecols=["id", "year", "title"])

    if args.validate:
        print(f'{"titulo":45} esperado detectado boxes')
        ok = True
        for t, y, exp, tol in VALIDATION:
            row = meta[(meta.title == t) & (meta.year == y)]
            if not len(row):
                print(f"{t:45} NO ENCONTRADO")
                continue
            r = detect(det, DATA / "posters" / f"{int(row.iloc[0].id)}.jpg")
            flag = "OK" if abs(r["n_faces"] - exp) <= tol else "FAIL"
            ok &= flag == "OK"
            print(
                f'{t:45} {exp:8} {r["n_faces"]:9} {flag}  '
                f'{r["face_boxes"][:40]}'
            )
        print("VALIDACION:", "PASA" if ok else "REVISAR")
        return

    if args.rebox and CHECKPOINT.exists():
        CHECKPOINT.unlink()
        print("checkpoint borrado (--rebox)")

    done = set(pd.read_csv(CHECKPOINT).id) if CHECKPOINT.exists() else set()
    todo = meta[~meta.id.isin(done)]
    print(f"pendientes: {len(todo):,}/{len(meta):,} (workers={args.workers})")
    t0, rows = time.time(), []
    jobs = [(pid, DATA / "posters" / f"{pid}.jpg", yr) for pid, yr in zip(todo.id, todo.year)]

    with ProcessPoolExecutor(max_workers=args.workers, initializer=_pool_init) as ex:
        futs = {ex.submit(_detect_one, j): j for j in jobs}
        n_seen = 0
        for fut in as_completed(futs):
            if args.budget and time.time() - t0 > args.budget:
                break
            n_seen += 1
            r = fut.result()
            if r is None:
                continue
            rows.append(r)
            if len(rows) % 500 == 0:
                pd.DataFrame(rows).to_csv(
                    CHECKPOINT,
                    mode="a",
                    header=not CHECKPOINT.exists(),
                    index=False,
                )
                done |= {r["id"] for r in rows}
                rate = n_seen / max(time.time() - t0, 1e-9)
                print(
                    f"  checkpoint +{len(rows):,} "
                    f"({len(done):,}/{len(meta):,}) {rate:.0f}/s",
                    flush=True,
                )
                rows = []
    if rows:
        pd.DataFrame(rows).to_csv(
            CHECKPOINT,
            mode="a",
            header=not CHECKPOINT.exists(),
            index=False,
        )
    total = len(set(pd.read_csv(CHECKPOINT).id)) if CHECKPOINT.exists() else 0
    print(
        f"total: {total:,}/{len(meta):,} | "
        f"{(total - len(done) + len(rows)) / max(time.time() - t0, 1e-9):.0f}/s"
    )

    if total >= len(meta):
        finalize(pd.read_csv(CHECKPOINT), out_csv, out_decade)


if __name__ == "__main__":
    main()
