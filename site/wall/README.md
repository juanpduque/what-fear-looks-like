# Wall cut — Archivo de pared

Standalone scrollytelling prototype for **What Fear Looks Like** / *Cómo se ve el miedo* (Pulp Analytics · Juan Pablo Duque). A framed poster hangs on a cinema wall and flips through six eras as you scroll.

This is **not** the live charts essay. The published piece stays at `site/index.html`. This folder is a second cut of the same thesis, using a Three.js poster-on-the-wall engine.

## Run it

From `site/`:

```bash
cd site
python3 -m http.server 8000
```

Then open:

- Live essay: http://localhost:8000/
- Wall cut: http://localhost:8000/wall/ or http://localhost:8000/wall/index.html

A discreet footer link on the essay (`Wall cut / Archivo de pared`) also points here.

## Prototype vs live essay

| | Live essay (`site/index.html`) | Wall cut (`site/wall/`) |
|---|---|---|
| Form | Charts, specimens, lookup | Native-scroll 3D poster + HTML |
| Stack | D3 + Scrollama | Three.js r160 + one rAF loop |
| Default language | EN (browser/localStorage) | ES, with one-click EN |
| Data | `site/data/series.js` + lookup | Same series, copied into the page |

Do not treat this folder as a replacement for the charts essay.

## Engine

- Native scroll (no hijack, no custom scrollbar, no `touch-action: none`).
- WebGL canvas behind (`#scene`); HTML UI on top (`#ui`).
- Camera poses blended by section visibility, then exponentially damped.
- Card flip: two `PlaneGeometry` faces back-to-back plus a thin `BoxGeometry` edge. Incoming era texture is assigned to the face that will look at the camera after ~90°.
- Mouse inertia on X/Z. 2D `<img>` fallback if Three.js or WebGL is missing.
- Film-countdown preloader with `pointer-events: none` and a timeout exit.
- Gauge is a **separate** 2D canvas (`#gauge`), never `getContext('2d')` on the WebGL canvas.
- `prefers-reduced-motion` skips the preloader and tightens lerps.

## Data

Published **n = 37,829** English-language horror posters (TMDB, 1897–2028). Series inlined here match `site/data/series.js` (color river, brightness, faces, MSER text-like coverage / “shout”, pixel-red, semantic blood). Copy uses 37,829 even if an older export header said ~37,842.

Illustrations in `images/` are **original** (generated for this cut). They are not studio posters and do not reproduce copyrighted one-sheets.

This product uses the TMDB API but is not endorsed or certified by TMDB.

## Files

```
site/wall/
  index.html          # CSS + app JS inline
  README.md
  vendor/three.min.js # official Three.js r160 min build
  images/
    hero-wall.png
    poster-1920s.png … poster-2010s.png
    grain.png         # overlay tile
```
