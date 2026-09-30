# Wall cut — Archivo de pared

Standalone scrollytelling for **What Fear Looks Like** / *Cómo se ve el miedo* (Pulp Analytics · Juan Pablo Duque). A framed poster hangs on a cinema wall; the scroll tells the essay as **six measurement acts**, then a fast recap of six illustrated eras.

This is **not** the live charts essay. The published method, lookup, and explorer stay at `site/index.html`. Each act links out with “cómo se midió.”

## Run it

From `site/`:

```bash
cd site
python3 -m http.server 8000
```

Then open:

- Live essay: http://localhost:8000/
- Wall cut: http://localhost:8000/wall/ or http://localhost:8000/wall/index.html
- VHS specimen demo: http://localhost:8000/demos/poster-decompose/

A discreet footer link on the essay (`Wall cut / Archivo de pared`) also points here.

## Prototype vs live essay

| | Live essay (`site/index.html`) | Wall cut (`site/wall/`) |
|---|---|---|
| Form | Full D3 grids, explorer, lookup | Native-scroll 3D poster + one chart/strip per act |
| Stack | D3 + Scrollama | Three.js r160 + D3 + one rAF loop |
| Default language | EN (browser/localStorage) | ES, with one-click EN |
| Data | `site/data/series.js` + lookup | Same `series.js` via `legacy-bridge.js` (no copied figures) |

Do not treat this folder as a replacement for the charts essay.

## Scroll spine

Hero + intro → Halloween specimen (CTA to the VHS demo) → Color → Darkness → Red / two bloods → Faces + census → Quieting (shout + symmetry/diagonal sparks) → Lettering → recap of six eras → face-to-face → close.

## Engine

- Native scroll (no hijack, no custom scrollbar, no `touch-action: none`).
- WebGL canvas behind (`#scene`); HTML UI on top (`#ui`).
- Camera poses blended by section visibility, then exponentially damped. Pose `evidence` ghosts the card behind the SVG.
- Card flip: two `PlaneGeometry` faces back-to-back plus a thin `BoxGeometry` edge. Incoming texture is assigned to the face that will look at the camera after ~90°.
- Gauge HUD (`#gauge`) swaps instrument per `data-needle` (`shout`, `bright`, `faces`, `red`, `blood`, `dark`, `ornate`). Never `getContext('2d')` on the WebGL canvas.
- Mouse inertia on X/Z. 2D `<img>` fallback if Three.js or WebGL is missing.
- Film-countdown preloader with `pointer-events: none` and a timeout exit.
- `prefers-reduced-motion` skips the preloader and tightens lerps.

## Data

Published **n = 37,829** English-language horror posters (TMDB, 1897–2028). Series come from `site/data/series.js`. Copy uses 37,829 even if an older export header said ~37,842.

Illustrations in `images/` are **original** (generated for this cut). They are not studio posters. `images/halloween.jpg` is the TMDB one-sheet for the specimen frame (id 948).

This product uses the TMDB API but is not endorsed or certified by TMDB.

## Files

```
site/wall/
  index.html
  wall.js             # 3D engine, gauge, D3 acts, strips
  README.md
  vendor/three.min.js # official Three.js r160 min build
  images/
    hero-wall.png
    poster-1920s.png … poster-2010s.png
    halloween.jpg
    grain.png
```
