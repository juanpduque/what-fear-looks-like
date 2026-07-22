#!/usr/bin/env python3
"""Title bounding boxes for the Dissect overlay via EasyOCR.

MSER text_area stays decade-comparable; it is a bad title localizer.
This script finds a title block with EasyOCR, scored against the TMDB title,
with a geometry fallback when recognition is messy but a title bar is obvious.

  python3 title_boxes.py                      # resume full corpus
  python3 title_boxes.py --retry-misses       # re-run rows with no box
  python3 title_boxes.py --ids 578,948 --merge --lookup
  python3 title_boxes.py --merge-only --lookup

Outputs: data/title_boxes.csv
"""
from __future__ import annotations

import argparse, re, time
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"
OUT = DATA / "title_boxes.csv"
POSTERS = DATA / "posters"

_READER = None


def _reader():
    global _READER
    if _READER is None:
        import easyocr
        _READER = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _READER


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _fuzzy_title(text: str, title: str) -> float:
    a, b = _norm(text), _norm(title)
    if not a or not b:
        return 0.0
    r = SequenceMatcher(None, a, b).ratio()
    # Containment only for real tokens (not single letters: E ⊂ ALIEN).
    if len(a) >= 3 and (a in b or b in a):
        r = max(r, 0.90)
    for w in re.findall(r"[A-Z0-9]+", (title or "").upper()):
        if len(w) < 3:
            continue
        if len(a) >= 3 and (w in a or a in w):
            r = max(r, 0.82 if len(w) >= 4 else 0.65)
        tw = SequenceMatcher(None, a, w).ratio()
        if tw >= 0.72 and len(a) >= 3:
            r = max(r, tw * 0.95)
    if len(a) <= 2:
        r *= 0.25
    return float(min(1.0, r))


def _pad_box(x0, y0, x1, y1, H, W, ocr="", score=0.0):
    pad_x, pad_y = 0.02 * W, 0.012 * H
    x0 = max(0.0, x0 - pad_x)
    y0 = max(0.0, y0 - pad_y)
    x1 = min(float(W), x1 + pad_x)
    y1 = min(float(H), y1 + pad_y)
    if (y1 - y0) / H > 0.34:
        return None
    if (x1 - x0) / W < 0.10:
        return None
    return {
        "text_x": round(x0 / W, 4),
        "text_top": round(y0 / H, 4),
        "text_w": round((x1 - x0) / W, 4),
        "text_h": round((y1 - y0) / H, 4),
        "ocr": (ocr or "")[:80],
        "score": round(float(score), 4),
    }


def _pos_bonus(cy: float) -> float:
    if cy < 0.28 or cy > 0.72:
        return 2.2
    if cy < 0.40 or cy > 0.60:
        return 1.2
    return 0.7


def _cluster_by_row(dets, H, y_gap=0.07):
    """Group detections into horizontal title lines / stacked blocks."""
    if not dets:
        return []
    ordered = sorted(dets, key=lambda d: (d["y0"] + d["y1"]) / 2)
    clusters = []
    cur = [ordered[0]]
    for d in ordered[1:]:
        cy = (d["y0"] + d["y1"]) / 2
        prev = sum((c["y0"] + c["y1"]) / 2 for c in cur) / len(cur)
        if abs(cy - prev) <= y_gap * H:
            cur.append(d)
        else:
            clusters.append(cur)
            cur = [d]
    clusters.append(cur)
    # Also try merging adjacent clusters into stacked titles (2–3 lines)
    stacked = list(clusters)
    for i in range(len(clusters) - 1):
        a, b = clusters[i], clusters[i + 1]
        ya = sum((c["y0"] + c["y1"]) / 2 for c in a) / len(a)
        yb = sum((c["y0"] + c["y1"]) / 2 for c in b) / len(b)
        if abs(yb - ya) <= 0.16 * H:
            stacked.append(a + b)
    return stacked


def _score_cluster(cluster, H, W, title):
    x0 = min(c["x0"] for c in cluster)
    y0 = min(c["y0"] for c in cluster)
    x1 = max(c["x1"] for c in cluster)
    y1 = max(c["y1"] for c in cluster)
    w, h = x1 - x0, y1 - y0
    if w < 8 or h < 5:
        return -1.0, 0.0, ""
    text = " ".join(c["text"] for c in sorted(cluster, key=lambda c: (c["y0"], c["x0"])))
    match = _fuzzy_title(text, title)
    # also max individual token match (SHINING in The Shining)
    match = max(match, max(c["match"] for c in cluster))
    conf = float(np.mean([c["conf"] for c in cluster]))
    cy = (y0 + y1) * 0.5 / H
    size = (w / W) * min((h / H) * 3.2, 1.5)
    score = (0.25 + 0.75 * conf) * (0.20 + 0.80 * match) * size * _pos_bonus(cy)
    score *= 1.0 + 0.08 * min(len(_norm(text)), 20)
    return score, match, text


def _best_recognition_box(dets, H, W, title):
    best = None
    best_s = -1.0
    for cluster in _cluster_by_row(dets, H):
        score, match, text = _score_cluster(cluster, H, W, title)
        conf = float(np.mean([c["conf"] for c in cluster]))
        # Accept if title-like OR strong OCR on a title-rail / wide band
        w = max(c["x1"] for c in cluster) - min(c["x0"] for c in cluster)
        cy = (min(c["y0"] for c in cluster) + max(c["y1"] for c in cluster)) * 0.5 / H
        wide = w / W >= 0.28
        rail = cy < 0.32 or cy > 0.68
        ok = (
            (match >= 0.55 and score >= 0.20)
            or (match >= 0.72 and conf >= 0.35)
            or (conf >= 0.80 and wide and rail and score >= 0.18)
        )
        if not ok:
            continue
        if score > best_s:
            x0 = min(c["x0"] for c in cluster)
            y0 = min(c["y0"] for c in cluster)
            x1 = max(c["x1"] for c in cluster)
            y1 = max(c["y1"] for c in cluster)
            box = _pad_box(x0, y0, x1, y1, H, W, ocr=text, score=score)
            if box:
                best, best_s = box, score
    return best


def _geometry_fallback(img, H, W, title):
    """When recognition is messy, still frame the widest title-rail detection."""
    reader = _reader()
    try:
        horiz, free = reader.detect(img)
    except Exception:
        return None
    cands = []
    if horiz:
        for item in horiz:
            # easyocr returns list of lists; shape varies by version
            boxes = item if item and isinstance(item[0], (list, tuple, np.ndarray)) else [item]
            for b in boxes:
                if b is None or len(b) < 4:
                    continue
                x0, x1, y0, y1 = map(float, b[:4])
                if x1 < x0:
                    x0, x1 = x1, x0
                if y1 < y0:
                    y0, y1 = y1, y0
                cands.append((x0, y0, x1, y1))
    if free:
        for item in free:
            polys = item if item and isinstance(item[0], (list, tuple, np.ndarray)) else [item]
            for poly in polys:
                try:
                    pts = np.array(poly).reshape(-1, 2)
                    x0, y0 = pts.min(axis=0)
                    x1, y1 = pts.max(axis=0)
                    cands.append((float(x0), float(y0), float(x1), float(y1)))
                except Exception:
                    continue

    best = None
    best_s = -1.0
    # merge nearby detect boxes into bands
    for x0, y0, x1, y1 in cands:
        w, h = x1 - x0, y1 - y0
        if w / W < 0.18 or h / H > 0.28 or h < 4:
            continue
        cy = (y0 + y1) * 0.5 / H
        aspect = w / max(h, 1)
        if aspect < 1.8:
            continue
        # Prefer rails; allow mid if very wide (Shining-like)
        if cy < 0.30 or cy > 0.70:
            pos = 2.0
        elif cy < 0.42 or cy > 0.60:
            pos = 1.0
        else:
            pos = 0.45 if w / W > 0.45 else 0.15
        score = (w / W) * min(aspect, 10) * pos
        if score > best_s:
            box = _pad_box(x0, y0, x1, y1, H, W, ocr=f"[detect] {title[:40]}", score=score)
            if box:
                best, best_s = box, score
    # Also merge all rail boxes into one band if several sit on same row
    for rail in ((0.0, 0.34), (0.66, 1.0)):
        band = [c for c in cands if rail[0] <= (c[1] + c[3]) / 2 / H <= rail[1]]
        if len(band) < 1:
            continue
        x0 = min(c[0] for c in band)
        y0 = min(c[1] for c in band)
        x1 = max(c[2] for c in band)
        y1 = max(c[3] for c in band)
        if (x1 - x0) / W < 0.22:
            continue
        score = 2.5 * ((x1 - x0) / W)
        box = _pad_box(x0, y0, x1, y1, H, W, ocr=f"[detect-band] {title[:40]}", score=score)
        if box and score > best_s:
            best, best_s = box, score
    return best if best_s >= 0.35 else None


def _dets_from_readtext(res, H, W, title):
    dets = []
    for box, text, conf in res:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, x1 = float(min(xs)), float(max(xs))
        y0, y1 = float(min(ys)), float(max(ys))
        match = _fuzzy_title(text, title)
        dets.append({
            "text": text, "conf": float(conf), "match": match,
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        })
    return dets


def locate_title(path: Path, title: str):
    img = cv2.imread(str(path))
    if img is None:
        return None
    H, W = img.shape[:2]
    reader = _reader()
    dets = _dets_from_readtext(
        reader.readtext(str(path), detail=1, paragraph=False), H, W, title
    )
    best = _best_recognition_box(dets, H, W, title)
    if best is not None and best["score"] >= 0.35:
        return best

    geo = _geometry_fallback(img, H, W, title)

    # Light boost pass only if both paths are weak
    if best is None and (geo is None or geo["score"] < 0.8):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        boost = cv2.cvtColor(
            cv2.merge([
                hsv[:, :, 0],
                cv2.max(hsv[:, :, 1], 180),
                cv2.max(hsv[:, :, 2], 160),
            ]),
            cv2.COLOR_HSV2BGR,
        )
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        boost = cv2.addWeighted(boost, 0.65, cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), 0.35, 0)
        dets2 = _dets_from_readtext(
            reader.readtext(boost, detail=1, paragraph=False), H, W, title
        )
        alt = _best_recognition_box(dets + dets2, H, W, title)
        if alt is not None and (best is None or alt["score"] > best["score"]):
            best = alt

    if best is not None and geo is not None:
        return best if best["score"] >= geo["score"] * 0.55 else geo
    return best or geo


def merge_into_attributes(boxes: pd.DataFrame, *, reset: bool = False):
    attr_path = DATA / "attributes.csv"
    df = pd.read_csv(attr_path)
    for c in ("text_x", "text_top", "text_w", "text_h"):
        if c not in df.columns:
            df[c] = -1.0
        if reset:
            df[c] = -1.0
    b = boxes.set_index("id")
    hit = df["id"].isin(b.index)
    for c in ("text_x", "text_top", "text_w", "text_h"):
        df.loc[hit, c] = df.loc[hit, "id"].map(b[c]).astype(float)
    df.to_csv(attr_path, index=False)

    partial = DATA / "attributes_partial.csv"
    if partial.exists():
        p = pd.read_csv(partial)
        for c in ("text_x", "text_top", "text_w", "text_h"):
            if c not in p.columns:
                p[c] = -1.0
            if reset:
                p[c] = -1.0
            p.loc[p["id"].isin(b.index), c] = (
                p.loc[p["id"].isin(b.index), "id"].map(b[c]).astype(float)
            )
        p.to_csv(partial, index=False)
    print(f"merged {int(hit.sum()):,} boxes into {attr_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="comma-separated TMDB ids")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--save-every", type=int, default=40)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--lookup", action="store_true")
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--retry-misses", action="store_true",
                    help="recompute rows that currently have no title box")
    ap.add_argument("--live-lookup", action="store_true",
                    help="rebuild lookup.js on every checkpoint save")
    args = ap.parse_args()

    if args.merge_only:
        merge_into_attributes(pd.read_csv(OUT), reset=True)
        if args.lookup:
            import build_lookup
            build_lookup.main()
        return

    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    if args.ids:
        want = {int(x) for x in args.ids.split(",") if x.strip()}
        meta = meta[meta.id.isin(want)]
    elif args.sample:
        meta = meta.sample(args.sample, random_state=42)

    existing = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame(
        columns=["id", "text_x", "text_top", "text_w", "text_h", "ocr", "score"]
    )
    rows = {int(r["id"]): dict(r) for r in existing.to_dict("records")} if len(existing) else {}

    if args.retry_misses:
        done = {i for i, r in rows.items() if float(r.get("text_x", -1)) >= 0}
    elif args.ids:
        done = set()
    else:
        done = set(rows)

    t0 = time.time()
    n_new = 0
    updated = []
    for r in meta.itertuples(index=False):
        pid = int(r.id)
        if pid in done:
            continue
        path = POSTERS / f"{pid}.jpg"
        if not path.exists():
            continue
        try:
            box = locate_title(path, str(r.title))
        except Exception as e:
            print(f"fail {pid}: {e}")
            box = None
        if box is None:
            row = dict(id=pid, text_x=-1.0, text_top=-1.0, text_w=-1.0, text_h=-1.0,
                       ocr="", score=0.0)
        else:
            row = dict(id=pid, **box)
        rows[pid] = row
        updated.append(pid)
        n_new += 1
        if n_new % 10 == 0:
            rate = n_new / max(time.time() - t0, 1e-6)
            print(f"{n_new} new | {pid} {str(r.title)[:28]!r} -> "
                  f"top={row['text_top']} ocr={row.get('ocr', '')!r} | {rate:.2f}/s",
                  flush=True)
        if n_new % args.save_every == 0:
            pd.DataFrame(rows.values()).to_csv(OUT, index=False)
            if args.merge or args.live_lookup:
                merge_into_attributes(pd.DataFrame(rows.values()), reset=False)
            if args.live_lookup:
                import build_lookup
                build_lookup.main()

    pd.DataFrame(rows.values()).to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(rows)} rows, {n_new} new, {time.time() - t0:.1f}s)")

    if args.merge or args.ids or args.retry_misses:
        chunk = pd.DataFrame([rows[i] for i in updated]) if updated else pd.read_csv(OUT)
        full = bool(args.merge and not args.ids and not args.sample and not args.retry_misses)
        merge_into_attributes(chunk if not full else pd.read_csv(OUT), reset=full)
    if args.lookup or args.live_lookup:
        import build_lookup
        build_lookup.main()


if __name__ == "__main__":
    main()
