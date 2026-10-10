#!/usr/bin/env python3
"""Body pose dynamism over movie posters -- is the figure static (portrait pose,
arms at sides) or dynamic (running, falling, reaching, fighting)? Two-stage
pipeline: YOLOv8n detects person bounding boxes, ViTPose (COCO 17-keypoint)
estimates the skeleton within each box.

Scoped to posters that already have a Rekognition-detected face (faces_v2*.csv,
n_faces > 0) -- posters with zero faces essentially never have a legible human
body either, so there's no point spending compute on the rest of the corpus.

Per-poster metrics (computed on the highest-confidence / largest detected person):
  n_persons            - how many people YOLOv8n found (0 if none -- expected
                         for e.g. Saw's severed-foot poster, not an error)
  kpt_bbox_area_frac    - bounding box area of all confident keypoints, normalized
                         by the person's own detection box area. Low = compact/
                         static pose (arms at sides); high = limbs spread out
                         (running, falling, reaching -- classic action pose)
  limb_asymmetry        - mean absolute left/right limb-position difference
                         relative to torso center, normalized by torso size.
                         Symmetric standing poses score low; mid-stride /
                         off-balance / struggling poses score high
  mean_kpt_confidence   - average keypoint detection confidence (sanity check;
                         low values mean the pose is unreliable, e.g. heavily
                         stylized/painted figure the model wasn't trained on)

Also persists the raw detection, for anything that wants to draw the
skeleton on the poster later instead of just the summary numbers above:
  box          - [x0, y0, x1, y1] of the YOLOv8n person box used, JSON-encoded
  keypoints    - the 17 COCO keypoints as [[x, y, score], ...] in that fixed
                 order (see NOSE..R_ANKLE below), JSON-encoded. Coordinates
                 are already in the original poster's pixel space (not
                 relative to `box`) -- post_process_pose_estimation() maps
                 them back itself, so these can be plotted directly over the
                 full poster image with no extra transform.
  img_w, img_h - pixel size of the poster that produced `box`/`keypoints`.
                 Needed to normalize for the autopsy overlay.

Usage (local smoke test):
  python3 vitpose_dynamism_score.py --ids-file data/qa/some_ids.txt --out /tmp/test.csv

EC2 shard:
  python3 vitpose_dynamism_score.py --ids-file data/qa/shard.txt --out data/qa/pose_score.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
POSTERS = DATA / "posters"

# COCO 17-keypoint order used by ViTPose
NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 1, 2, 3, 4
L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW = 5, 6, 7, 8
L_WRIST, R_WRIST, L_HIP, R_HIP = 9, 10, 11, 12
L_KNEE, R_KNEE, L_ANKLE, R_ANKLE = 13, 14, 15, 16
LEFT_RIGHT_PAIRS = [(L_SHOULDER, R_SHOULDER), (L_ELBOW, R_ELBOW), (L_WRIST, R_WRIST),
                    (L_HIP, R_HIP), (L_KNEE, R_KNEE), (L_ANKLE, R_ANKLE)]

KPT_CONF_THRESHOLD = 0.3
MAX_PERSONS = 12


def load_faces() -> set[int]:
    """Union of data/faces_v2.csv + _scifi/_thriller/_mystery (non-partial),
    ids with n_faces > 0 -- see clip_face_expression.py for the original pattern."""
    ids: set[int] = set()
    files = [DATA / "faces_v2.csv", DATA / "faces_v2_scifi.csv",
             DATA / "faces_v2_thriller.csv", DATA / "faces_v2_mystery.csv"]
    for f in files:
        if not f.exists():
            continue
        df = pd.read_csv(f, usecols=["id", "n_faces"])
        ids |= set(int(i) for i in df[df.n_faces > 0]["id"])
    return ids


def compute_metrics(keypoints: np.ndarray, scores: np.ndarray, box: list[float]) -> dict:
    x0, y0, x1, y1 = box
    box_w, box_h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    box_area = box_w * box_h

    conf_mask = scores >= KPT_CONF_THRESHOLD
    mean_conf = float(scores.mean())
    if conf_mask.sum() < 3:
        return {"kpt_bbox_area_frac": None, "limb_asymmetry": None, "mean_kpt_confidence": round(mean_conf, 3)}

    pts = keypoints[conf_mask]
    kpt_x0, kpt_y0 = pts[:, 0].min(), pts[:, 1].min()
    kpt_x1, kpt_y1 = pts[:, 0].max(), pts[:, 1].max()
    kpt_bbox_area_frac = ((kpt_x1 - kpt_x0) * (kpt_y1 - kpt_y0)) / box_area

    torso_size = max(box_w, box_h)
    if scores[L_SHOULDER] >= KPT_CONF_THRESHOLD and scores[R_SHOULDER] >= KPT_CONF_THRESHOLD and \
       scores[L_HIP] >= KPT_CONF_THRESHOLD and scores[R_HIP] >= KPT_CONF_THRESHOLD:
        center = (keypoints[L_SHOULDER] + keypoints[R_SHOULDER] + keypoints[L_HIP] + keypoints[R_HIP]) / 4
    else:
        center = pts.mean(axis=0)

    diffs = []
    for li, ri in LEFT_RIGHT_PAIRS:
        if scores[li] >= KPT_CONF_THRESHOLD and scores[ri] >= KPT_CONF_THRESHOLD:
            dl = np.linalg.norm(keypoints[li] - center)
            dr = np.linalg.norm(keypoints[ri] - center)
            diffs.append(abs(dl - dr) / torso_size)
    limb_asymmetry = float(np.mean(diffs)) if diffs else None

    return {
        "kpt_bbox_area_frac": round(float(kpt_bbox_area_frac), 4),
        "limb_asymmetry": round(limb_asymmetry, 4) if limb_asymmetry is not None else None,
        "mean_kpt_confidence": round(mean_conf, 3),
    }


def encode_kpts(kpts, scores) -> list[list[float]]:
    return [
        [round(float(x), 1), round(float(y), 1), round(float(s), 3)]
        for (x, y), s in zip(kpts.tolist(), scores.tolist())
    ]


def primary_index(boxes: list, metrics: list[dict], img_w: int, img_h: int) -> int:
    """Prefer a standing foreground figure over a crowd-merge blob (Freaks 136)."""
    img_area = max(float(img_w * img_h), 1.0)
    best_i, best = 0, -1.0
    for i, box in enumerate(boxes):
        x0, y0, x1, y1 = (float(c) for c in box)
        bw, bh = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        area = (bw * bh) / img_area
        aspect = bh / bw
        met = metrics[i] if i < len(metrics) else {}
        conf = float(met.get("mean_kpt_confidence") or 0.0)
        spread = met.get("kpt_bbox_area_frac")
        crowd = 0.12 if area >= 0.18 and spread is not None and spread < 0.35 else 1.0
        cy = ((y0 + y1) / 2) / max(img_h, 1)
        vert = 1.15 if cy < 0.62 else 0.7
        size = min(area / 0.04, 1.6)
        score = (0.25 + conf) * min(aspect, 2.2) * crowd * vert * size
        if score > best:
            best, best_i = score, i
    return best_i


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--checkpoint-every", type=int, default=50)
    ap.add_argument("--posters-dir", default=str(POSTERS))
    ap.add_argument("--no-face-filter", action="store_true",
                    help="process every id in --ids-file (already scoped upstream)")
    ap.add_argument("--all-boxes", action="store_true",
                    help="ViTPose every YOLO person (cap MAX_PERSONS); persist persons JSON")
    args = ap.parse_args()

    from ultralytics import YOLO
    from transformers import AutoProcessor, VitPoseForPoseEstimation

    print("loading YOLOv8n (person detector)...", flush=True)
    yolo = YOLO("yolov8n.pt")
    print("loading ViTPose...", flush=True)
    processor = AutoProcessor.from_pretrained("usyd-community/vitpose-base-simple")
    model = VitPoseForPoseEstimation.from_pretrained("usyd-community/vitpose-base-simple").eval()

    posters_dir = Path(args.posters_dir)
    want_ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip()]
    if args.no_face_filter:
        print("face filter: skipped (--no-face-filter)", flush=True)
    else:
        face_ids = load_faces()
        print(f"posters with faces (union of 4 genres): {len(face_ids):,}", flush=True)
        want_ids = [i for i in want_ids if i in face_ids]
    want_ids = [i for i in want_ids if (posters_dir / f"{i}.jpg").exists()]
    print(f"todo: {len(want_ids):,}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[int] = set()
    if out.exists() and out.stat().st_size > 0:
        try:
            done_ids = set(pd.read_csv(out)["id"])
        except Exception:
            done_ids = set()
        want_ids = [i for i in want_ids if i not in done_ids]
        print(f"resume: {len(done_ids):,} already done, {len(want_ids):,} remaining", flush=True)

    new_file = not out.exists()
    fields = ["id", "n_persons", "kpt_bbox_area_frac", "limb_asymmetry", "mean_kpt_confidence",
              "img_w", "img_h", "box", "keypoints"]
    if args.all_boxes:
        fields = fields + ["persons"]
    if not new_file:
        existing_header = out.open(newline="", encoding="utf-8").readline().strip().split(",")
        if existing_header != fields:
            raise SystemExit(
                f"{out} already exists with a different schema -- "
                f"appending new rows with more columns than the existing header would corrupt "
                f"it. Point --out at a new file, or migrate the old one first."
            )
    f_out = out.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_out, fieldnames=fields)
    if new_file:
        writer.writeheader()
        f_out.flush()

    t0 = time.time()
    n_done = 0
    n_err = 0
    for pid in want_ids:
        try:
            p = posters_dir / f"{pid}.jpg"
            img = Image.open(p).convert("RGB")
            w, h = img.size
            yres = yolo(str(p), classes=[0], verbose=False)
            boxes = yres[0].boxes.xyxy.cpu().numpy().tolist() if yres[0].boxes is not None else []
            row = {"id": pid, "n_persons": len(boxes),
                   "kpt_bbox_area_frac": "", "limb_asymmetry": "", "mean_kpt_confidence": "",
                   "img_w": w, "img_h": h, "box": "", "keypoints": ""}
            if args.all_boxes:
                row["persons"] = ""
            if boxes:
                boxes.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
                use = boxes[:MAX_PERSONS] if args.all_boxes else boxes[:1]
                inputs = processor(img, boxes=[use], return_tensors="pt")
                with torch.no_grad():
                    outputs = model(**inputs)
                results = processor.post_process_pose_estimation(outputs, boxes=[use])
                detected = results[0]
                packed = []
                for box, person in zip(use, detected):
                    kpts = person["keypoints"].numpy()
                    scores = person["scores"].numpy()
                    met = compute_metrics(kpts, scores, box)
                    packed.append({
                        "box": [round(float(c), 1) for c in box],
                        "keypoints": encode_kpts(kpts, scores),
                        "metrics": met,
                    })
                mets = [p["metrics"] for p in packed]
                idx = primary_index(use, mets, w, h) if args.all_boxes else 0
                chosen = packed[idx]
                row.update({k: (v if v is not None else "") for k, v in chosen["metrics"].items()})
                row["box"] = json.dumps(chosen["box"])
                row["keypoints"] = json.dumps(chosen["keypoints"])
                if args.all_boxes:
                    row["persons"] = json.dumps([
                        {
                            "box": p["box"],
                            "keypoints": p["keypoints"],
                            "conf": p["metrics"].get("mean_kpt_confidence"),
                        }
                        for p in packed
                    ], separators=(",", ":"))
            writer.writerow(row)
        except Exception as e:
            n_err += 1
            if n_err <= 5:
                print(f"  FAIL {pid}: {e}", flush=True)
            continue
        n_done += 1
        if n_done % args.checkpoint_every == 0 or n_done == len(want_ids):
            f_out.flush()
            rate = n_done / max(time.time() - t0, 1e-9)
            print(f"  {n_done:,}/{len(want_ids):,} rate={rate:.1f}/s err={n_err}", flush=True)

    f_out.close()
    print(f"LISTO {len(done_ids) + n_done:,} total, err={n_err}", flush=True)


if __name__ == "__main__":
    main()
