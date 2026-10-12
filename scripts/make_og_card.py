#!/usr/bin/env python3
"""Render site/assets/og-card.jpg, the 1200x630 image shown when the essay is shared.

The poster count and year range are read from site/data/explorer.js, so rerun
this whenever the corpus changes:

  python3 scripts/make_og_card.py

Renders an HTML card in headless Chrome (Playwright) with the essay's fonts and
palette; needs network for Google Fonts and the TMDB poster.
"""
from __future__ import annotations

import base64
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT = SITE / "assets" / "og-card.jpg"
LOGO = SITE / "assets" / "pulp-analytics-red.png"
# Halloween (1978), TMDB id 948 — the essay's anchor specimen.
POSTER = "https://image.tmdb.org/t/p/w780/wijlZ3HaYMvlDTPqJoTCWKFkCPU.jpg"


def corpus_stats() -> tuple[int, int, int]:
    js = (SITE / "data" / "explorer.js").read_text(encoding="utf-8")
    n = int(re.search(r"n=(\d+)", js).group(1))
    years = [int(y) for y in re.findall(r"\[(\d{4}),\"#", js)]
    if len(years) != n:
        sys.exit(f"explorer.js header says n={n} but {len(years)} rows were parsed")
    return n, min(years), max(years)


def html(n: int, y0: int, y1: int) -> str:
    logo = base64.b64encode(LOGO.read_bytes()).decode()
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Source+Serif+4:ital,wght@0,400;1,400&family=Space+Mono:wght@400;700&display=block" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1200px;height:630px;overflow:hidden;color:#e8e4da;
  background:radial-gradient(ellipse 100% 90% at 60% 45%,#12161e 0%,#07080b 62%,#030408 100%)}}
.card{{display:flex;align-items:center;gap:64px;height:100%;padding:0 72px 0 72px}}
.poster{{flex:none;width:330px;height:495px;border:2px solid #c1121f;padding:10px;background:#000}}
.poster img{{width:100%;height:100%;object-fit:cover;display:block}}
.text{{flex:1;border-left:4px solid #c1121f;padding-left:36px}}
.kicker{{font:700 15px 'Space Mono',monospace;letter-spacing:.28em;text-transform:uppercase;color:#c1121f}}
h1{{font:400 104px/0.95 'Anton',sans-serif;text-transform:uppercase;margin:18px 0 26px}}
h1 .fear{{color:#c1121f}}
.dek{{font:400 30px/1.3 'Source Serif 4',serif}}
.dek b{{font-weight:400;color:#e5a00d}}
.tag{{font:italic 400 24px/1.35 'Source Serif 4',serif;color:#9a958a;margin-top:14px}}
.logo{{position:absolute;right:56px;bottom:40px;height:58px}}
</style></head><body><div class="card">
<div class="poster"><img src="{POSTER}" alt=""></div>
<div class="text">
  <p class="kicker">A poster analysis</p>
  <h1>What <span class="fear">Fear</span><br>Looks Like</h1>
  <p class="dek"><b>{n:,}</b> horror posters measured, {y0}–{y1}</p>
  <p class="tag">Horror didn't get scarier. It got quieter.</p>
</div></div>
<img class="logo" src="data:image/png;base64,{logo}" alt="">
</body></html>"""


def main() -> None:
    n, y0, y1 = corpus_stats()
    with tempfile.TemporaryDirectory() as tmp:
        page_path = Path(tmp) / "card.html"
        page_path.write_text(html(n, y0, y1), encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            page = browser.new_page(viewport={"width": 1200, "height": 630})
            page.goto(page_path.as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_function("document.querySelector('.poster img').complete")
            page.screenshot(path=str(OUT), type="jpeg", quality=88)
            browser.close()
    print(f"wrote {OUT} (n={n:,}, {y0}–{y1}, {OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
