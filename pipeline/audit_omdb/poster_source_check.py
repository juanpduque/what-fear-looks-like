"""Is the IMDb poster (via OMDb's Poster API) the same art as the TMDB poster the essay measured?

500 corpus films (decade-stratified, with an IMDb id). For each: the TMDB sheet the site shows
(w780) and the IMDb poster (Poster API, h=1000), compared with the pHash the corpus uses
(distance <= 10 = same art, see docs/METRIC_AGREEMENTS.md). Says nothing about which one is the
release-year art; it only tells whether the two sources agree.
Images are not stored. Key: $OMDB_API_KEY or ~/.omdb_key.
Run from pipeline/: python3 audit_omdb/poster_source_check.py [--n 500] [--seed 11]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from omdb_pilot import api_key, sample
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
OUT = HERE / "results" / "poster_source_check.jsonl"
SAME = 10


def explorer_paths() -> dict[int, str]:
    js = (HERE.parent.parent / "site" / "data" / "explorer.js").read_text(encoding="utf-8")
    rows = json.loads(js[js.index("[[") : js.rindex("]]") + 2])
    return {r[7]: r[2] for r in rows}


def get(url: str) -> Image.Image:
    req = urllib.request.Request(url, headers={"User-Agent": "what-fear-looks-like research"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGB")


def compare(row, key: str, paths: dict[int, str]) -> dict:
    from build_poster_images import hamming, phash  # noqa: PLC0415 - needs sys.path set above

    rec = {
        "id": int(row.id),
        "imdb_id": row.imdb_id,
        "year": int(row.year),
        "decade": int(row.decade),
    }
    if not paths.get(int(row.id)):
        return {**rec, "err": "no TMDB path"}
    try:
        t = get("https://image.tmdb.org/t/p/w780" + paths[int(row.id)])
        q = urllib.parse.urlencode({"apikey": key, "i": row.imdb_id, "h": 1000})
        i = get("https://img.omdbapi.com/?" + q)
        rec.update(dist=hamming(phash(t), phash(i)), tmdb_size=list(t.size), imdb_size=list(i.size))
    except Exception as e:
        rec["err"] = f"{type(e).__name__}: {e}"[:80]
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    key, paths = api_key(), explorer_paths()
    OUT.parent.mkdir(exist_ok=True)
    done = set()
    if OUT.exists():
        done = {json.loads(x)["id"] for x in OUT.read_text().splitlines()}
    todo = sample(args.n, args.seed)
    todo = [r for r in todo.itertuples() if int(r.id) not in done]
    with OUT.open("a") as f, ThreadPoolExecutor(4) as ex:
        for rec in ex.map(lambda r: compare(r, key, paths), todo):
            f.write(json.dumps(rec) + "\n")
            f.flush()
    df = pd.DataFrame([json.loads(x) for x in OUT.read_text().splitlines()])
    ok = df[df["dist"].notna()].copy()
    ok["same"] = ok["dist"] <= SAME
    print(f"{len(df)} films, {len(ok)} compared, {len(df) - len(ok)} failed")
    print(f"same art (pHash <= {SAME}): {ok['same'].mean():.0%} ({ok['same'].sum()}/{len(ok)})")
    print(ok.groupby("decade")["same"].agg(["mean", "size"]).round(2).T.to_string())


if __name__ == "__main__":
    main()
