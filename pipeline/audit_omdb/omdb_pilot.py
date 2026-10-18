"""OMDb pilot: how much of the corpus can OMDb enrich, and with what?

Draws a decade-stratified sample of corpus films that have an IMDb id, asks OMDb for each
(Rated, Metascore, Rotten Tomatoes, Awards, Country, Language, Released, Director, Actors) and
reports coverage per field and decade. Raw responses stay local (results/ is git-ignored):
OMDb data is CC BY-NC, so per-film values must not be committed.

The key is read from $OMDB_API_KEY or ~/.omdb_key, never from the command line.
Run (from pipeline/): python3 audit_omdb/omdb_pilot.py [--n 500] [--seed 7]
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUT = HERE / "results" / "omdb_pilot.jsonl"
FIELDS = [
    "Rated",
    "Metascore",
    "RT",
    "Awards",
    "Country",
    "Language",
    "Released",
    "Director",
    "Actors",
]


def api_key() -> str:
    key = os.environ.get("OMDB_API_KEY")
    if not key and (Path.home() / ".omdb_key").exists():
        key = (Path.home() / ".omdb_key").read_text().strip()
    if not key:
        raise SystemExit("Set OMDB_API_KEY or write the key to ~/.omdb_key")
    return key


def fetch(imdb_id: str, key: str) -> dict:
    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode({"i": imdb_id, "apikey": key})
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def sample(n: int, seed: int) -> pd.DataFrame:
    ids = set(map(int, (DATA / "canonical_ids.txt").read_text().split()))
    imdb = pd.read_csv(DATA / "imdb_ids.csv").dropna()
    imdb = imdb[imdb["id"].isin(ids)].drop_duplicates("id")
    # year comes from the published explorer so the pilot runs without the external disk
    js = (HERE.parent.parent / "site" / "data" / "explorer.js").read_text(encoding="utf-8")
    rows = json.loads(js[js.index("[[") : js.rindex("]]") + 2])
    attrs = pd.DataFrame({"id": [r[7] for r in rows], "year": [r[0] for r in rows]})
    df = imdb.merge(attrs, on="id")
    df["decade"] = (df["year"] // 10 * 10).astype(int)
    per = max(1, n // df["decade"].nunique())
    return (
        df.groupby("decade", group_keys=False)
        .apply(lambda g: g.sample(min(len(g), per), random_state=seed))
        .reset_index(drop=True)
    )


def flatten(r: dict) -> dict:
    rt = next((x["Value"] for x in r.get("Ratings", []) if x["Source"] == "Rotten Tomatoes"), None)
    row = {k: r.get(k) for k in FIELDS if k != "RT"}
    row["RT"] = rt
    return {k: (None if v in (None, "N/A") else v) for k, v in row.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    key = api_key()
    OUT.parent.mkdir(exist_ok=True)
    done = set()
    if OUT.exists():
        done = {json.loads(line)["id"] for line in OUT.read_text().splitlines()}
    todo = sample(args.n, args.seed)
    todo = todo[~todo["id"].isin(done)]
    with OUT.open("a") as f:
        for row in todo.itertuples():
            r = fetch(row.imdb_id, key)
            if r.get("Error") and "limit" in r["Error"].lower():
                raise SystemExit(f"OMDb: {r['Error']} (done {len(done)})")
            rec = {
                "id": int(row.id),
                "imdb_id": row.imdb_id,
                "year": int(row.year),
                "decade": int(row.decade),
            }
            rec["ok"] = r.get("Response") == "True"
            rec.update(flatten(r) if rec["ok"] else {})
            f.write(json.dumps(rec) + "\n")
            f.flush()
            time.sleep(0.1)
    df = pd.DataFrame([json.loads(x) for x in OUT.read_text().splitlines()])
    print(f"{len(df)} films, {df['ok'].mean():.0%} found by OMDb")
    cov = df.groupby("decade")[FIELDS].agg(lambda s: s.notna().mean()).round(2)
    cov.insert(0, "n", df.groupby("decade").size())
    print(cov.to_string())
    print("\noverall coverage:", df[FIELDS].notna().mean().round(2).to_dict())


if __name__ == "__main__":
    main()
