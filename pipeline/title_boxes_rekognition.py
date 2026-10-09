#!/usr/bin/env python3
"""Title bounding boxes via AWS Rekognition DetectText.

Same job as title_boxes.py (EasyOCR), but uses a managed API: words/lines +
bounding boxes. ~$0.001/image → ~$28 for the full corpus.

Requires: aws configure (region us-east-1), boto3, network.

  python3 title_boxes_rekognition.py --ids 578,948 --merge --lookup
  python3 title_boxes_rekognition.py --merge --lookup          # resume full
  python3 title_boxes_rekognition.py --retry-misses --merge --lookup

Outputs: data/title_boxes_rekognition.csv
         (optional merge into attributes.csv text_x/top/w/h)
"""
from __future__ import annotations

import argparse, re, time
from difflib import SequenceMatcher
from pathlib import Path

import boto3
import pandas as pd
from botocore.exceptions import ClientError

DATA = Path(__file__).parent / "data"
OUT = DATA / "title_boxes_rekognition.csv"
POSTERS = DATA / "posters"
REGION = "us-east-1"


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _fuzzy_title(text: str, title: str) -> float:
    a, b = _norm(text), _norm(title)
    if not a or not b:
        return 0.0
    r = SequenceMatcher(None, a, b).ratio()
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


def _boxed_lines(lines: list[dict]) -> list[tuple[tuple[float, ...], str]]:
    boxed = []
    for ln in lines:
        box = ln.get("box") if isinstance(ln, dict) else None
        if not isinstance(box, (list, tuple)) or len(box) < 4:
            continue
        try:
            b = tuple(float(v) for v in box[:4])
        except (TypeError, ValueError):
            continue
        boxed.append((b, ln.get("text") or ""))
    return boxed


def _multi_line_rows(boxed: list[tuple]) -> list[list[tuple]]:
    """Lines sharing a text row, left to right; only rows with 2+ lines."""
    rows: list[list[tuple]] = []
    for b, text in sorted(boxed, key=lambda x: x[0][1] + x[0][3] / 2):
        cy, h = b[1] + b[3] / 2, b[3]
        for row in rows:
            rb = row[0][0]
            if abs(cy - (rb[1] + rb[3] / 2)) <= 0.6 * max(h, rb[3]):
                row.append((b, text))
                break
        else:
            rows.append([(b, text)])
    out = []
    for row in rows:
        if len(row) >= 2:
            row.sort(key=lambda x: x[0][0])
            out.append(row)
    return out


def title_line_hits(lines: list[dict], title: str, min_match: float):
    """DetectText lines that spell the title, as [(match, box, text)].

    Letter-spaced titles ("A L I E N") come back as one line per letter, and
    no single letter fuzzy-matches the title. When no line matches alone,
    group lines sharing a row (left to right) and match the joined text.
    """
    boxed = _boxed_lines(lines)
    hits = []
    for b, text in boxed:
        m = _fuzzy_title(text, title)
        if m >= min_match:
            hits.append((m, b, text))
    if hits:
        return hits

    best = None
    for row in _multi_line_rows(boxed):
        joined = " ".join(text for _, text in row)
        m = _fuzzy_title(joined, title)
        if m >= min_match and (best is None or m > best[0]):
            best = (m, row, joined)
    if best is None:
        return []
    m, row, joined = best
    return [(m, b, joined) for b, _ in row]


def aka_line_hits(lines: list[dict], akas, min_ratio: float = 0.8):
    """Like title_line_hits, but for alternative release titles (AKAs).

    _fuzzy_title's substring bonus is too loose for long or foreign AKAs (a
    director's name inside "Psicosis de Alfred Hitchcock" scores 0.90), so a
    line or row must match a whole AKA by plain sequence ratio.
    """
    boxed = _boxed_lines(lines)
    cands = [[bt] for bt in boxed] + _multi_line_rows(boxed)
    best = None
    for aka in akas:
        target = _norm(aka)
        if len(target) < 3:
            continue
        for cand in cands:
            joined = " ".join(text for _, text in cand)
            m = SequenceMatcher(None, _norm(joined), target).ratio()
            if m >= min_ratio and (best is None or m > best[0]):
                best = (m, cand, joined)
    if best is None:
        return []
    m, cand, joined = best
    return [(m, b, joined) for b, _ in cand]


def _pos_bonus(cy: float) -> float:
    if cy < 0.28 or cy > 0.72:
        return 2.2
    if cy < 0.40 or cy > 0.60:
        return 1.2
    return 0.7


def _client():
    return boto3.client("rekognition", region_name=REGION)


def detect_lines(client, path: Path):
    """Return list of LINE detections with normalized boxes."""
    data = path.read_bytes()
    if len(data) > 5_000_000:
        # Rekognition bytes limit is 5MB; compress via Pillow if ever needed
        raise ValueError(f"image too large: {len(data)} bytes")
    resp = client.detect_text(Image={"Bytes": data})
    lines = []
    for d in resp.get("TextDetections", []):
        if d.get("Type") != "LINE":
            continue
        bb = d["Geometry"]["BoundingBox"]
        lines.append({
            "text": d.get("DetectedText", ""),
            "conf": float(d.get("Confidence", 0)) / 100.0,
            "x0": float(bb["Left"]),
            "y0": float(bb["Top"]),
            "x1": float(bb["Left"] + bb["Width"]),
            "y1": float(bb["Top"] + bb["Height"]),
        })
    return lines


def locate_title(client, path: Path, title: str):
    try:
        lines = detect_lines(client, path)
    except ClientError as e:
        print(f"aws error {path.stem}: {e}")
        return None
    if not lines:
        return None

    # Score each line; also try merging nearby lines (stacked titles)
    cands = []
    for ln in lines:
        match = _fuzzy_title(ln["text"], title)
        w = ln["x1"] - ln["x0"]
        h = ln["y1"] - ln["y0"]
        cy = (ln["y0"] + ln["y1"]) * 0.5
        size = w * min(h * 3.2, 1.5)
        score = (0.25 + 0.75 * ln["conf"]) * (0.15 + 0.85 * match) * size * _pos_bonus(cy)
        score *= 1.0 + 0.08 * min(len(_norm(ln["text"])), 20)
        cands.append({**ln, "match": match, "score": score})

    # stacked merge: lines within 0.12 vertical of best seed
    cands.sort(key=lambda c: -c["score"])
    seed = cands[0]
    cluster = [seed]
    y_mid = (seed["y0"] + seed["y1"]) * 0.5
    for c in cands[1:]:
        cy = (c["y0"] + c["y1"]) * 0.5
        if abs(cy - y_mid) > 0.14:
            continue
        if c["match"] >= 0.45 or c["conf"] >= 0.80 or abs(cy - y_mid) <= 0.06:
            cluster.append(c)
            y_mid = sum((x["y0"] + x["y1"]) * 0.5 for x in cluster) / len(cluster)

    match = max(_fuzzy_title(
        " ".join(c["text"] for c in sorted(cluster, key=lambda c: (c["y0"], c["x0"]))),
        title,
    ), max(c["match"] for c in cluster))
    conf = sum(c["conf"] for c in cluster) / len(cluster)
    x0 = min(c["x0"] for c in cluster)
    y0 = min(c["y0"] for c in cluster)
    x1 = max(c["x1"] for c in cluster)
    y1 = max(c["y1"] for c in cluster)
    w, h = x1 - x0, y1 - y0
    cy = (y0 + y1) * 0.5
    score = (0.25 + 0.75 * conf) * (0.15 + 0.85 * match) * w * min(h * 3.2, 1.5) * _pos_bonus(cy)

    # Accept: good title match, OR confident wide rail text
    rail = cy < 0.32 or cy > 0.68
    ok = (
        (match >= 0.55 and score >= 0.08)
        or (match >= 0.72)
        or (conf >= 0.85 and w >= 0.25 and rail)
        or (conf >= 0.90 and w >= 0.35)
    )
    if not ok:
        return None
    if h > 0.34 or w < 0.08:
        return None

    # pad
    pad_x, pad_y = 0.02, 0.012
    x0 = max(0.0, x0 - pad_x)
    y0 = max(0.0, y0 - pad_y)
    x1 = min(1.0, x1 + pad_x)
    y1 = min(1.0, y1 + pad_y)
    ocr = " ".join(c["text"] for c in sorted(cluster, key=lambda c: (c["y0"], c["x0"])))
    return {
        "text_x": round(x0, 4),
        "text_top": round(y0, 4),
        "text_w": round(x1 - x0, 4),
        "text_h": round(y1 - y0, 4),
        "ocr": ocr[:80],
        "score": round(score, 4),
    }


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
    print(f"merged {int(hit.sum()):,} boxes into {attr_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--save-every", type=int, default=100)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--lookup", action="store_true")
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--retry-misses", action="store_true")
    ap.add_argument("--live-lookup", action="store_true")
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

    client = _client()
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
            box = locate_title(client, path, str(r.title))
        except Exception as e:
            print(f"fail {pid}: {e}", flush=True)
            box = None
        if box is None:
            row = dict(id=pid, text_x=-1.0, text_top=-1.0, text_w=-1.0, text_h=-1.0,
                       ocr="", score=0.0)
        else:
            row = dict(id=pid, **box)
        rows[pid] = row
        updated.append(pid)
        n_new += 1
        if n_new % 20 == 0:
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
        full = bool(args.merge and not args.ids and not args.sample and not args.retry_misses)
        chunk = pd.DataFrame([rows[i] for i in updated]) if updated and not full else pd.read_csv(OUT)
        merge_into_attributes(chunk, reset=full)
    if args.lookup or args.live_lookup:
        import build_lookup
        build_lookup.main()


if __name__ == "__main__":
    main()
