import csv
import io
import json
import os
import sys
import time

import requests
from PIL import Image

sys.path.insert(0, ".")
from build_poster_images import hamming, phash

OUT = sys.argv[1]
canon = set(open("data/canonical_ids.txt").read().split())
yr = {
    r["id"]: int(float(r["year"]))
    for r in csv.DictReader(open("data/posters.csv"))
    if r["id"] in canon and r["year"]
}
rows = []
for r in csv.DictReader(open("data/impawards_credits.csv")):
    i = r["id"]
    if i in yr and 1930 <= yr[i] <= 1999 and r["poster_image_urls"].startswith("http"):
        rows.append(
            (
                i,
                yr[i],
                r["poster_image_urls"].split(";")[0].split(",")[0].strip(),
                r["title"],
                r.get("matched_year", ""),
            )
        )
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        done.add(json.loads(l)["id"])
H = {"User-Agent": "what-fear-looks-like research (poster provenance check)"}
print("por comparar:", len([r for r in rows if r[0] not in done]), "de", len(rows), flush=True)
for i, y, url, t, my in rows:
    if i in done:
        continue
    rec = {"id": i, "year": y, "title": t, "url": url, "matched_year": my}
    try:
        r = requests.get(url, headers=H, timeout=30)
        if r.status_code != 200:
            rec["err"] = r.status_code
        else:
            a = Image.open(io.BytesIO(r.content)).convert("RGB")
            b = Image.open(f"data/posters/{i}.jpg").convert("RGB")
            rec["dist"] = hamming(phash(a), phash(b))
            rec["impa_size"] = list(a.size)
            rec["tmdb_size"] = list(b.size)
    except Exception as e:
        rec["err"] = f"{type(e).__name__}"[:40]
    with open(OUT, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    time.sleep(1.0)
print("FIN", flush=True)
