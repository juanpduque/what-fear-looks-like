#!/usr/bin/env python3
"""Render the 1200x630 images shown when the essay is shared: site/assets/og-card.jpg
(English, used by index.html) and og-card-es.jpg (Spanish, used by es/index.html).

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
# Card copy per language: (output file, kicker, title HTML, count line, tagline).
CARDS = {
    "en": (
        "og-card.jpg",
        "A poster analysis",
        'What <span class="fear">Fear</span><br>Looks Like',
        "<b>{n}</b> horror posters measured, {y0}–{y1}",
        "Horror didn't get scarier. It got quieter.",
    ),
    "es": (
        "og-card-es.jpg",
        "Un análisis de afiches",
        'Cómo se ve<br>el <span class="fear">miedo</span>',
        "<b>{n}</b> afiches de terror, de {y0} a {y1}",
        "El terror bajó la voz.",
    ),
}
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


def html(lang: str, n: int, y0: int, y1: int) -> str:
    _, kicker, title, count, tag = CARDS[lang]
    logo = base64.b64encode(LOGO.read_bytes()).decode()
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
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
  <p class="kicker">{kicker}</p>
  <h1>{title}</h1>
  <p class="dek">{count.format(n=f"{n:,}", y0=y0, y1=y1)}</p>
  <p class="tag">{tag}</p>
</div></div>
<img class="logo" src="data:image/png;base64,{logo}" alt="">
</body></html>"""


def main() -> None:
    n, y0, y1 = corpus_stats()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        for lang, (name, *_) in CARDS.items():
            out = SITE / "assets" / name
            page_path = Path(tmp) / f"card-{lang}.html"
            page_path.write_text(html(lang, n, y0, y1), encoding="utf-8")
            page.goto(page_path.as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_function("document.querySelector('.poster img').complete")
            page.screenshot(path=str(out), type="jpeg", quality=88)
            print(f"wrote {out} (n={n:,}, {y0}–{y1}, {out.stat().st_size // 1024} KB)")
        browser.close()


if __name__ == "__main__":
    main()
