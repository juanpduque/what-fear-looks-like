#!/usr/bin/env python3
"""Build side-by-side review for TMDB primary-poster drift.

Reads data/poster_path_drift.csv (from validate_poster_paths.py) and writes
site/poster-drift-review.html — frozen path vs current TMDB primary.

  python3 build_poster_drift_review.py
  open ../site/poster-drift-review.html
"""
from __future__ import annotations

import csv
import html
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SRC = DATA / "poster_path_drift.csv"
OUT = ROOT.parent / "site" / "poster-drift-review.html"
IMG = "https://image.tmdb.org/t/p/w342"


def main():
    if not SRC.exists():
        raise SystemExit(f"missing {SRC} — run validate_poster_paths.py first")

    rows = []
    with SRC.open(newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("status") != "ok" or r.get("match") != "0":
                continue
            if not (r.get("stored_path") or "").startswith("/"):
                continue
            if not (r.get("current_path") or "").startswith("/"):
                continue
            try:
                year = int(float(r["year"]))
            except (TypeError, ValueError):
                year = 0
            rows.append({
                "id": int(r["id"]),
                "title": r.get("title") or "",
                "year": year,
                "stored": r["stored_path"],
                "current": r["current_path"],
            })

    rows.sort(key=lambda r: (r["year"], r["title"].lower()))
    by_dec: dict[int, list] = defaultdict(list)
    for r in rows:
        by_dec[(r["year"] // 10) * 10].append(r)

    cards = []
    for dec in sorted(by_dec):
        cards.append(f'<div class="dec-head">{dec}s · {len(by_dec[dec])}</div>')
        for r in by_dec[dec]:
            title = html.escape(r["title"])
            cards.append(
                f'<article class="card" data-id="{r["id"]}">'
                f'<div class="pair">'
                f'<figure><img loading="lazy" src="{IMG}{html.escape(r["stored"])}" alt="">'
                f'<figcaption>congelado</figcaption></figure>'
                f'<figure><img loading="lazy" src="{IMG}{html.escape(r["current"])}" alt="">'
                f'<figcaption>TMDB hoy</figcaption></figure>'
                f'</div>'
                f'<div class="cap"><b>{title}</b><br>{r["year"]} · id {r["id"]}<br>'
                f'<a href="https://www.themoviedb.org/movie/{r["id"]}" target="_blank" rel="noopener">ficha TMDB</a>'
                f'</div></article>'
            )

    n = len(rows)
    body = "\n".join(cards)
    OUT.write_text(
        f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Poster drift — {n} desajustes</title>
<style>
body{{background:#0a0a0c;color:#e8e4da;font-family:-apple-system,sans-serif;margin:0;padding:24px}}
h1{{font-size:20px;font-weight:600;margin:0 0 8px}}
.lede{{color:#9a958a;font-size:13px;max-width:720px;line-height:1.45;margin:0 0 20px}}
.toolbar{{position:sticky;top:0;background:#0a0a0c;padding:12px 0;z-index:10;
  border-bottom:1px solid #2a2a30;margin-bottom:16px;font-size:13px;color:#9a958a}}
.toolbar b{{color:#e5a00d}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}}
.dec-head{{grid-column:1/-1;font-size:13px;letter-spacing:.08em;text-transform:uppercase;
  color:#e5a00d;margin:22px 0 4px;border-bottom:1px solid #2a2a30;padding-bottom:4px}}
.card{{background:#141416;border-radius:6px;overflow:hidden;border:1px solid #222}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:2px;background:#0a0a0c}}
.pair figure{{margin:0}}
.pair img{{width:100%;aspect-ratio:2/3;object-fit:cover;display:block;background:#1a1a1e}}
.pair figcaption{{font-size:9px;letter-spacing:.1em;text-transform:uppercase;text-align:center;
  color:#9a958a;padding:4px 0;background:#141416}}
.cap{{font-size:11px;line-height:1.35;color:#9a958a;padding:8px 10px}}
.cap b{{color:#e8e4da;font-size:12px}}
.cap a{{color:#e5a00d}}
</style></head><body>
<div class="toolbar"><b>{n}</b> pósters donde el path congelado ≠ póster principal actual en TMDB
 · los JPGs locales del essay siguen siendo los de la izquierda</div>
<h1>Revision: portada oficial vs la que medimos</h1>
<p class="lede">Izquierda: <code>poster_path</code> congelado (lo que analizamos / CDN de ese path).
Derecha: póster principal que TMDB muestra hoy. No implica que el JPG local esté “mal” —
TMDB a menudo rota el arte promocional después del freeze.</p>
<div class="grid">
{body}
</div>
</body></html>
""",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({n} mismatches)")


if __name__ == "__main__":
    main()
