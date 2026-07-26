#!/usr/bin/env python3
"""Pilot: title OCR via Google Cloud Vision TEXT_DETECTION.

Stratified sample by decade (~500 posters). Uses Application Default Credentials
and project playground-ia-502703 (override with GCP_PROJECT / --project).

  python3 title_boxes_vision_pilot.py
  python3 title_boxes_vision_pilot.py --n 500 --workers 8

Outputs:
  data/title_boxes_vision_pilot.csv
  data/title_boxes_vision_pilot_summary.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "title_boxes_vision_pilot.csv"
SUMMARY = DATA / "title_boxes_vision_pilot_summary.json"
POSTERS = DATA / "posters"
DEFAULT_PROJECT = "playground-ia-502703"
VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


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


def _pos_bonus(cy: float) -> float:
    if cy < 0.28 or cy > 0.72:
        return 2.2
    if cy < 0.40 or cy > 0.60:
        return 1.2
    return 0.7


def _token() -> str:
    return subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"],
        text=True,
    ).strip()


def stratified_sample(meta: pd.DataFrame, n: int, seed: int = 42) -> pd.DataFrame:
    d = meta[(meta.year >= 1897) & (meta.year <= 2030)].copy()
    d["decade"] = (d.year // 10) * 10
    decades = sorted(d.decade.unique())
    # equal budget per decade, leftover to largest decades
    base = max(1, n // len(decades))
    parts = []
    for dec in decades:
        g = d[d.decade == dec]
        k = min(len(g), base)
        parts.append(g.sample(k, random_state=seed) if k < len(g) else g)
    sample = pd.concat(parts, ignore_index=True)
    leftover = n - len(sample)
    if leftover > 0:
        rest = d[~d.id.isin(sample.id)]
        # prefer decades with more films left
        if len(rest):
            take = min(leftover, len(rest))
            # weight by decade size
            w = rest.groupby("decade")["id"].transform("count")
            extra = rest.sample(take, random_state=seed + 1, weights=w)
            sample = pd.concat([sample, extra], ignore_index=True)
    return sample.drop_duplicates("id").head(n)


def vision_lines(session: requests.Session, token: str, project: str,
                 path: Path) -> tuple[list[dict], str, int, int]:
    """Return (word/line-like boxes normalized, full_text, W, H)."""
    raw = path.read_bytes()
    # Vision accepts larger than Rekognition; still cap insane sizes
    if len(raw) > 20_000_000:
        raise ValueError(f"image too large: {len(raw)}")
    r = session.post(
        VISION_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "x-goog-user-project": project,
        },
        json={
            "requests": [{
                "image": {"content": base64.b64encode(raw).decode()},
                "features": [{"type": "TEXT_DETECTION"}],
            }]
        },
        timeout=60,
    )
    if r.status_code == 401:
        raise SystemExit("Vision 401 — re-run: gcloud auth application-default login")
    if r.status_code == 429:
        time.sleep(2)
        return vision_lines(session, token, project, path)
    if not r.ok:
        raise RuntimeError(f"Vision HTTP {r.status_code}: {r.text[:200]}")
    resp = (r.json().get("responses") or [{}])[0]
    if "error" in resp:
        raise RuntimeError(resp["error"])
    anns = resp.get("textAnnotations") or []
    if not anns:
        return [], "", 0, 0

    # First annotation is full text; rest are tokens/words with boxes
    full = anns[0].get("description") or ""
    # infer image size from first poly if possible (Vision returns absolute px)
    verts = anns[0].get("boundingPoly", {}).get("vertices") or []
    # Better: use max x/y across all vertices as image bounds proxy
    xs, ys = [], []
    for a in anns:
        for v in a.get("boundingPoly", {}).get("vertices") or []:
            if "x" in v:
                xs.append(int(v["x"]))
            if "y" in v:
                ys.append(int(v["y"]))
    W = max(xs) + 1 if xs else 1
    H = max(ys) + 1 if ys else 1

    # Prefer paragraph/block grouping: Vision word anns are fine; also
    # split full text by newlines as line candidates when boxes exist.
    lines = []
    for a in anns[1:]:
        text = (a.get("description") or "").strip()
        if not text:
            continue
        vs = a.get("boundingPoly", {}).get("vertices") or []
        if len(vs) < 2:
            continue
        xs_ = [int(v.get("x", 0)) for v in vs]
        ys_ = [int(v.get("y", 0)) for v in vs]
        x0, x1 = min(xs_) / W, max(xs_) / W
        y0, y1 = min(ys_) / H, max(ys_) / H
        lines.append({
            "text": text,
            "conf": 0.9,  # Vision word anns don't always expose conf here
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        })
    return lines, full, W, H


def locate_title(session, token, project, path: Path, title: str):
    lines, full, W, H = vision_lines(session, token, project, path)
    if not lines and not full:
        return None

    # Build line-like candidates: individual words + nearby merges + full lines
    # from newline-split of full text matched to covering boxes
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

    # Merge words into pseudo-lines by y proximity
    if lines:
        by_y = sorted(lines, key=lambda c: (round(c["y0"] * 40), c["x0"]))
        buckets: list[list[dict]] = []
        for ln in by_y:
            if not buckets:
                buckets.append([ln])
                continue
            cy = (ln["y0"] + ln["y1"]) * 0.5
            last = buckets[-1]
            lcy = sum((x["y0"] + x["y1"]) * 0.5 for x in last) / len(last)
            if abs(cy - lcy) <= 0.045:
                last.append(ln)
            else:
                buckets.append([ln])
        for bucket in buckets:
            text = " ".join(b["text"] for b in sorted(bucket, key=lambda c: c["x0"]))
            x0 = min(b["x0"] for b in bucket)
            y0 = min(b["y0"] for b in bucket)
            x1 = max(b["x1"] for b in bucket)
            y1 = max(b["y1"] for b in bucket)
            match = _fuzzy_title(text, title)
            w, h = x1 - x0, y1 - y0
            cy = (y0 + y1) * 0.5
            size = w * min(h * 3.2, 1.5)
            conf = 0.9
            score = (0.25 + 0.75 * conf) * (0.15 + 0.85 * match) * size * _pos_bonus(cy)
            score *= 1.0 + 0.08 * min(len(_norm(text)), 20)
            cands.append({
                "text": text, "conf": conf, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "match": match, "score": score,
            })

    if not cands:
        # fall back: full text match without geometry
        match = _fuzzy_title(full.replace("\n", " "), title)
        if match < 0.55:
            return None
        return {
            "text_x": -1.0, "text_top": -1.0, "text_w": -1.0, "text_h": -1.0,
            "ocr": full.replace("\n", " ")[:80],
            "score": round(match, 4),
            "match": round(match, 4),
            "full_ocr": full[:500],
            "n_tokens": 0,
            "hit": 0,
        }

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

    ocr = " ".join(c["text"] for c in sorted(cluster, key=lambda c: (c["y0"], c["x0"])))
    match = max(
        _fuzzy_title(ocr, title),
        max(c["match"] for c in cluster),
        _fuzzy_title(full.replace("\n", " "), title),
    )
    conf = sum(c["conf"] for c in cluster) / len(cluster)
    x0 = min(c["x0"] for c in cluster)
    y0 = min(c["y0"] for c in cluster)
    x1 = max(c["x1"] for c in cluster)
    y1 = max(c["y1"] for c in cluster)
    w, h = x1 - x0, y1 - y0
    cy = (y0 + y1) * 0.5
    score = (0.25 + 0.75 * conf) * (0.15 + 0.85 * match) * w * min(h * 3.2, 1.5) * _pos_bonus(cy)

    rail = cy < 0.32 or cy > 0.68
    ok = (
        (match >= 0.55 and score >= 0.08)
        or (match >= 0.72)
        or (conf >= 0.85 and w >= 0.25 and rail)
        or (conf >= 0.90 and w >= 0.35)
        or (_fuzzy_title(full.replace("\n", " "), title) >= 0.72 and w >= 0.15)
    )
    hit = int(ok and h <= 0.34 and w >= 0.08)
    pad_x, pad_y = 0.02, 0.012
    return {
        "text_x": round(max(0.0, x0 - pad_x), 4) if hit else -1.0,
        "text_top": round(max(0.0, y0 - pad_y), 4) if hit else -1.0,
        "text_w": round(min(1.0, x1 + pad_x) - max(0.0, x0 - pad_x), 4) if hit else -1.0,
        "text_h": round(min(1.0, y1 + pad_y) - max(0.0, y0 - pad_y), 4) if hit else -1.0,
        "ocr": ocr[:80],
        "score": round(score, 4),
        "match": round(match, 4),
        "full_ocr": full[:500],
        "n_tokens": len(lines),
        "hit": hit,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--project", default=os.environ.get("GCP_PROJECT", DEFAULT_PROJECT))
    ap.add_argument("--limit", type=int, default=0, help="debug: only first N of sample")
    args = ap.parse_args()

    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    prev = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame()
    have = set(prev["id"].astype(int)) if len(prev) else set()

    sample = stratified_sample(meta, args.n, seed=args.seed)
    if args.limit:
        sample = sample.head(args.limit)
    # Pull in as many prior pilot ids as possible (don't waste billed calls)
    if len(prev) and not args.limit:
        prior_in = meta[meta.id.isin(have) & ~meta.id.isin(sample.id)]
        if len(prior_in):
            n_swap = min(len(prior_in), len(sample))
            drop = sample.sample(n_swap, random_state=args.seed + 7)
            sample = pd.concat(
                [sample[~sample.id.isin(drop.id)], prior_in.head(n_swap)],
                ignore_index=True,
            )
    sample = sample.drop_duplicates("id").head(args.n)
    todo = sample[~sample.id.isin(have)].copy()
    print(
        f"target={len(sample):,} reuse={len(have & set(sample.id.astype(int))):,} "
        f"to_fetch={len(todo):,}"
    )
    print(sample.assign(decade=sample.year // 10 * 10).groupby("decade").size().to_string())

    token = _token()
    token_lock = threading.Lock()
    token_holder = {"t": token, "t0": time.time()}

    def get_token():
        with token_lock:
            if time.time() - token_holder["t0"] > 2400:
                token_holder["t"] = _token()
                token_holder["t0"] = time.time()
            return token_holder["t"]

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=args.workers, pool_maxsize=args.workers)
    session.mount("https://", adapter)

    sample_ids = set(sample.id.astype(int))
    rows: list[dict] = [
        r for r in (prev.to_dict("records") if len(prev) else [])
        if int(r["id"]) in sample_ids
    ]
    lock = threading.Lock()
    done = 0
    hits = sum(int(r.get("hit") or 0) for r in rows)
    t0 = time.time()

    def work(row):
        pid = int(row.id)
        path = POSTERS / f"{pid}.jpg"
        if not path.exists():
            return {
                "id": pid, "title": row.title, "year": int(row.year),
                "text_x": -1.0, "text_top": -1.0, "text_w": -1.0, "text_h": -1.0,
                "ocr": "", "score": 0.0, "match": 0.0, "full_ocr": "",
                "n_tokens": 0, "hit": 0, "error": "missing_file",
            }
        try:
            box = locate_title(session, get_token(), args.project, path, str(row.title))
        except Exception as e:
            return {
                "id": pid, "title": row.title, "year": int(row.year),
                "text_x": -1.0, "text_top": -1.0, "text_w": -1.0, "text_h": -1.0,
                "ocr": "", "score": 0.0, "match": 0.0, "full_ocr": "",
                "n_tokens": 0, "hit": 0, "error": f"{type(e).__name__}: {e}",
            }
        if box is None:
            box = {
                "text_x": -1.0, "text_top": -1.0, "text_w": -1.0, "text_h": -1.0,
                "ocr": "", "score": 0.0, "match": 0.0, "full_ocr": "",
                "n_tokens": 0, "hit": 0,
            }
        return {"id": pid, "title": row.title, "year": int(row.year), "error": "", **box}

    total_fetch = len(todo)
    if total_fetch == 0:
        print("nothing new to fetch")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, r) for r in todo.itertuples(index=False)]
        for fut in as_completed(futs):
            row = fut.result()
            with lock:
                rows.append(row)
                done += 1
                hits += int(row.get("hit") or 0)
                if done % 50 == 0 or done == total_fetch:
                    rate = done / max(time.time() - t0, 1e-6)
                    print(
                        f"  fetch {done}/{total_fetch} total_hits≈{hits} "
                        f"{rate:.1f}/s",
                        flush=True,
                    )
                    pd.DataFrame(rows).drop_duplicates("id", keep="last").to_csv(
                        OUT, index=False
                    )

    df = pd.DataFrame(rows).sort_values("id")
    df.to_csv(OUT, index=False)

    # Compare vs existing attributes text_* if present
    attr = pd.read_csv(DATA / "attributes.csv", usecols=lambda c: c in (
        "id", "text_area", "text_x", "text_top", "text_w", "text_h"
    ))
    m = df.merge(attr, on="id", how="left", suffixes=("", "_attr"))
    m["decade"] = (m.year // 10) * 10
    by_dec = (
        m.groupby("decade")
        .agg(n=("id", "count"), hit_rate=("hit", "mean"),
             mean_match=("match", "mean"), mean_tokens=("n_tokens", "mean"))
        .round(3)
        .reset_index()
    )
    has_attr_box = (
        m["text_x_attr"].fillna(-1).astype(float) >= 0
        if "text_x_attr" in m.columns else pd.Series([False] * len(m))
    )
    summary = {
        "n": int(len(df)),
        "hits": int(df.hit.sum()),
        "hit_rate": round(float(df.hit.mean()), 4),
        "mean_match": round(float(df["match"].mean()), 4),
        "any_ocr_text": int((df.full_ocr.fillna("").str.len() > 0).sum()),
        "errors": int((df.error.fillna("") != "").sum()),
        "cost_usd_est": round(max(0, len(df) - 1000) / 1000 * 1.50, 2),
        # first 1000/mo free; this month already used ~500 on the first pilot
        "by_decade": by_dec.to_dict(orient="records"),
        "overlap_existing_attr_boxes": int((df.hit.astype(bool) & has_attr_box).sum())
            if len(has_attr_box) == len(df) else None,
        "vision_hit_attr_miss": int((df.hit.astype(bool) & ~has_attr_box).sum())
            if len(has_attr_box) == len(df) else None,
        "attr_hit_vision_miss": int((~df.hit.astype(bool) & has_attr_box).sum())
            if len(has_attr_box) == len(df) else None,
        "project": args.project,
        "output": str(OUT.name),
    }
    SUMMARY.write_text(json.dumps(summary, indent=2))
    print(f"\n=== VISION OCR PILOT ===")
    print(f"n={summary['n']} hits={summary['hits']} ({100*summary['hit_rate']:.1f}%)")
    print(f"any OCR text={summary['any_ocr_text']} errors={summary['errors']}")
    print(f"est. cost ≈ ${summary['cost_usd_est']} (pilot within free tier → ~$0)")
    print(by_dec.to_string(index=False))
    print(f"wrote {OUT.name} + {SUMMARY.name}")


if __name__ == "__main__":
    main()
