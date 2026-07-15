#!/usr/bin/env python3
"""
Persiste la metadata de las películas 1920-1949 (poster_path, vote_count)
en horror_movies.csv — el backfill original solo las usó en memoria.
  python3 backfill_meta.py --api-key TU_KEY     (~30 segundos)
"""
import argparse, time
from pathlib import Path
import pandas as pd
import requests

DATA = Path(__file__).parent / "data"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", required=True)
    args = ap.parse_args()
    rows, page, total = [], 1, 1
    while page <= total:
        r = requests.get("https://api.themoviedb.org/3/discover/movie",
                         params={"api_key": args.api_key, "with_genres": 27,
                                 "page": page, "sort_by": "primary_release_date.asc",
                                 "primary_release_date.gte": "1920-01-01",
                                 "primary_release_date.lte": "1949-12-31"},
                         timeout=30)
        r.raise_for_status()
        j = r.json(); total = j.get("total_pages", 1)
        for m in j.get("results", []):
            rows.append(dict(id=m["id"], title=m.get("title"),
                             original_title=m.get("original_title"),
                             release_date=m.get("release_date"),
                             poster_path=m.get("poster_path"),
                             vote_average=m.get("vote_average"),
                             vote_count=m.get("vote_count"),
                             popularity=m.get("popularity")))
        page += 1; time.sleep(0.05)
    new = pd.DataFrame(rows).dropna(subset=["poster_path", "release_date"])
    base = pd.read_csv(DATA / "horror_movies.csv")
    merged = pd.concat([base, new[~new.id.isin(base.id)]], ignore_index=True)
    merged.to_csv(DATA / "horror_movies.csv", index=False)
    print(f"añadidas {len(merged)-len(base):,} películas pre-1950 -> horror_movies.csv ({len(merged):,} total)")

if __name__ == "__main__":
    main()
