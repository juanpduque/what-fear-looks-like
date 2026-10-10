#!/usr/bin/env python3
"""Site data for the key art studios page and the autopsy credit line.

Reads the verified credits (verify_impawards_credits.py) and writes:
  site/data/studios.json  {n_corpus, n_verified, studios: [{credit, n,
                           impawards_total, posters: [[id, title, year, path]]}]}
  site/data/key_art.json  {id: credit}

"LA" is IMPAwards' label for uncredited agency work, so it is neither ranked
nor shown as a credit. impawards_total (all IMPAwards credits, any genre) comes
from data/impawards_designer_horror_counts.csv when present.

  python3 export_key_art.py
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from corpus import canonical_ids

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SITE_DATA = HERE.parent / "site" / "data"
VERIFIED = DATA / "qa" / "impawards_credit_verify.csv"
TOTALS = DATA / "impawards_designer_horror_counts.csv"
UNCREDITED = {"LA"}
MIN_POSTERS = 10


def main() -> None:
    keep = canonical_ids()
    text = (SITE_DATA / "explorer.js").read_text(encoding="utf-8")
    rows = json.loads(text[text.index("const POSTERS=") + 14:].rstrip().rstrip(";"))
    meta = {r[7]: (r[3], r[0], r[2] or None) for r in rows}

    credits: dict[int, str] = {}
    for r in csv.DictReader(VERIFIED.open(encoding="utf-8")):
        pid = int(r["id"])
        if r["verdict"] == "keep" and pid in keep and r["designer"] not in UNCREDITED:
            credits[pid] = r["designer"]

    totals = {}
    if TOTALS.is_file():
        for r in csv.DictReader(TOTALS.open(encoding="utf-8")):
            totals[r["name"]] = int(r["total_impawards_credits"])

    by_studio: dict[str, list[int]] = defaultdict(list)
    for pid, credit in credits.items():
        by_studio[credit].append(pid)
    studios = []
    for credit, ids in by_studio.items():
        if len(ids) < MIN_POSTERS:
            continue
        ids.sort(key=lambda i: (-meta[i][1], meta[i][0]))
        studios.append({
            "credit": credit,
            "n": len(ids),
            "impawards_total": totals.get(credit),
            "posters": [[i, meta[i][0], meta[i][1], meta[i][2]] for i in ids],
        })
    studios.sort(key=lambda s: (-s["n"], s["credit"].lower()))

    out = {"n_corpus": len(keep), "n_verified": len(credits), "studios": studios}
    (SITE_DATA / "studios.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (SITE_DATA / "key_art.json").write_text(
        json.dumps({str(k): v for k, v in sorted(credits.items())}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"studios.json: {len(studios)} studios (>= {MIN_POSTERS} posters); key_art.json: {len(credits):,} credits")
    for s in studios[:15]:
        print(f"  {s['n']:3d}  {s['credit']}")


if __name__ == "__main__":
    main()
