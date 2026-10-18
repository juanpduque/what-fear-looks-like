"""OCR check of the MSER text measure (attributes.csv text_area).

For a decade-stratified sample of the corpus, run EasyOCR and measure how much of each sheet the
detected text covers (union of word boxes), how many boxes it finds and how tall the biggest
one is. These come from a reader that sees letters, so they test whether text_area (MSER
glyph-like regions) follows real text.

  python3 audit_text_measure/ocr_text_share.py out.jsonl [per_decade=60]

Resumable: rerun with the same output file and it skips posters already measured.
"""

import csv
import json
import random
import sys
from pathlib import Path

import cv2
import easyocr
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MIN_CONF = 0.3
WIDTH = 640
DECADES = range(1930, 2030, 10)


def sample(per_decade, seed=0):
    keep = set(DATA.joinpath("canonical_ids.txt").read_text().split())
    by = {d: [] for d in DECADES}
    with (DATA / "attributes.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            d = int(float(r["year"])) // 10 * 10
            if r["id"] in keep and d in by:
                by[d].append(r["id"])
    rng = random.Random(seed)
    out = []
    for ids in by.values():
        ids = sorted(set(ids))
        out += rng.sample(ids, min(per_decade, len(ids)))
    return out


def measure(reader, path):
    img = cv2.imread(str(path))
    h, w = img.shape[:2]
    img = cv2.resize(img, (WIDTH, round(h * WIDTH / w)))
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    tallest, n = 0.0, 0
    for box, _text, conf in reader.readtext(img):
        if conf < MIN_CONF:
            continue
        pts = np.array(box, np.int32)
        cv2.fillPoly(mask, [pts], 1)
        tallest = max(tallest, (pts[:, 1].max() - pts[:, 1].min()) / h)
        n += 1
    return {
        "ocr_area": round(float(mask.mean()), 4),
        "ocr_boxes": n,
        "ocr_tallest": round(tallest, 4),
    }


def main(out_path, per_decade=60):
    out = Path(out_path)
    done = set()
    if out.exists():
        done = {json.loads(line)["id"] for line in out.open()}
    todo = [i for i in sample(per_decade) if i not in done]
    print("to measure:", len(todo), flush=True)
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    for k, pid in enumerate(todo):
        rec = {"id": pid}
        try:
            rec.update(measure(reader, DATA / "posters" / f"{pid}.jpg"))
        except Exception as e:
            rec["err"] = f"{type(e).__name__}: {e}"[:120]
        with out.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        if k % 50 == 0:
            print(k, flush=True)
    print("FIN", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 60)
