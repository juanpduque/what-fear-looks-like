#!/usr/bin/env python3
"""Verify IMPAwards poster-design credits against the film they were matched to.

pull_impawards_credits.py finds IMPAwards pages by guessing /<year>/<slug>.html
(also year ±1). For common titles that lands on a different film with the same
name (Disney's Wish credited to the horror Wish), so 13% of credits were wrong.

Per credited corpus film:
  1. If the IMPAwards page links an IMDb title, keep the credit only when it
     equals the film's IMDb id (data/imdb_ids.csv). Decides ~95% of credits.
  2. Otherwise keep it when the IMPAwards poster is close to one of the film's
     TMDB posters (64-bit dHash distance <= 23; unrelated images sit near 32)
     or the release year matched exactly. Checked against the IMDb-decided
     credits, this rule is right ~94% of the time.

Pages and images are cached (polite: ~4 requests/s to IMPAwards).

  python3 verify_impawards_credits.py --cache /tmp/impawards_cache
Writes data/qa/impawards_credit_verify.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from corpus import canonical_ids

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CREDITS = DATA / "impawards_credits.csv"
IMDB_IDS = DATA / "imdb_ids.csv"
SITE_DATA = HERE.parent / "site" / "data"
OUT = DATA / "qa" / "impawards_credit_verify.csv"
UA = "Mozilla/5.0 (research; what-fear-looks-like)"
TMDB = "https://image.tmdb.org/t/p/w342"
CLOSE_MAX = 23
FIELDS = ["id", "title", "year", "matched_year", "designer", "impawards_url",
          "page_imdb", "film_imdb", "dhash_dist", "verdict", "reason"]

_lock = threading.Lock()
_last = [0.0]


def fetch(url: str, cache: Path, polite: bool) -> bytes:
    fn = cache / hashlib.md5(url.encode()).hexdigest()
    if fn.exists():
        return fn.read_bytes()
    if polite:
        with _lock:
            wait = 0.25 - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=30).read()
    fn.write_bytes(data)
    return data


def dhash(data: bytes, n: int = 8) -> np.ndarray:
    g = np.asarray(Image.open(io.BytesIO(data)).convert("L").resize((n + 1, n), Image.LANCZOS), dtype=np.int16)
    return (g[:, 1:] > g[:, :-1]).flatten()


def tmdb_paths() -> dict[str, list[str]]:
    text = (SITE_DATA / "explorer.js").read_text(encoding="utf-8")
    rows = json.loads(text[text.index("const POSTERS=") + 14:].rstrip().rstrip(";"))
    paths = {str(r[7]): [r[2]] if r[2] else [] for r in rows}
    for pid, alts in json.loads((SITE_DATA / "poster_alts.json").read_text(encoding="utf-8")).items():
        for alt in alts:
            if alt[0] not in paths.setdefault(pid, []):
                paths[pid].append(alt[0])
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True, help="dir for cached pages/images")
    args = ap.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)

    keep = {str(i) for i in canonical_ids()}
    imdb = {r["id"]: r["imdb_id"] for r in csv.DictReader(IMDB_IDS.open(encoding="utf-8"))}
    paths = tmdb_paths()
    rows = [
        r for r in csv.DictReader(CREDITS.open(encoding="utf-8"))
        if r["id"] in keep and r["status"] == "matched" and r["poster_designer"].strip()
    ]

    def one(r: dict) -> dict:
        out = {k: r.get(k, "") for k in ("id", "title", "year", "matched_year", "impawards_url")}
        out["designer"] = r["poster_designer"].strip()
        out["film_imdb"] = imdb.get(r["id"], "")
        try:
            html = fetch(r["impawards_url"], args.cache, polite=True).decode("latin-1")
            page_ids = sorted(set(re.findall(r"imdb\.com/title/(tt\d{7,8})", html)))
        except OSError:
            page_ids = []
        out["page_imdb"] = "|".join(page_ids)
        dist = 64
        try:
            ih = dhash(fetch(r["poster_image_urls"].split("|")[0], args.cache, polite=True))
            for p in paths.get(r["id"], []):
                try:
                    dist = min(dist, int((ih != dhash(fetch(TMDB + p, args.cache, polite=False))).sum()))
                except OSError:
                    continue
        except OSError:
            pass
        out["dhash_dist"] = dist
        if page_ids and out["film_imdb"]:
            ok = out["film_imdb"] in page_ids
            out["reason"] = "imdb_match" if ok else "imdb_mismatch"
        else:
            ok = dist <= CLOSE_MAX or r["year"] == r["matched_year"]
            out["reason"] = ("image_close" if dist <= CLOSE_MAX else "year_exact") if ok else "no_evidence"
        out["verdict"] = "keep" if ok else "drop"
        return out

    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(one, rows))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(results, key=lambda x: int(x["id"])))
    kept = sum(r["verdict"] == "keep" for r in results)
    print(f"wrote {OUT} credits={len(results):,} keep={kept:,} drop={len(results) - kept:,}")


if __name__ == "__main__":
    main()
