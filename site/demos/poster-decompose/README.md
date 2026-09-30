# VHS Decompose — Halloween (teachable demo)

Scroll-driven Three.js: *Halloween* (1978) clamshell VHS in 3D. The sleeve uses **flat corpus art** (`poster.jpg`). Physical box photos (`vhs_reference*.png`) are mood board only — **never** cover albedo.

Bilingual UI (EN/ES): reads `?lang=` and `localStorage` key `aof-lang` (same as the essay).

## Open

```bash
cd site && python3 -m http.server 8765
```

→ [http://localhost:8765/demos/poster-decompose/](http://localhost:8765/demos/poster-decompose/)

(Serve from `site/` so ES modules + relative assets resolve.)

## 10 beats (long holds)

| Beat | Progress | What happens |
|---|---|---|
| **Hero** | 0–12% | Videoclub aisle → pull Halloween off the shelf |
| **Read** | 12–26% | Front view + OCR bbox · HALLOWEEN conf 0.98 |
| **Faces** | 26–38% | YuNet 0 faces · creature 0.35 |
| **Palette** | 38–52% | Five sleeve swatches + UV handles · 87% dark |
| **Symmetry** | 52–64% | Axis overlay · symmetry 0.93 |
| **Diagonals** | 64–74% | X guides · diagonal_score 0.20 |
| **Blood** | 74–82% | Nova blood 0.85 · red heat bbox |
| **Knife** | 82–90% | Nova knife 0.95 chip on sleeve |
| **Archive** | 90–100% | Lid opens → vintage VCR enters → tape inserts → essay CTA |

No chaotic explode. One dominant layer at a time.

## Assets

| File | Role |
|---|---|
| `poster.jpg` | **Cover albedo** (aspect measured on load, ~500×750) |
| `metrics.json` | Beats + `raw` corpus fields (TMDB 948) |
| `i18n.json` | EN/ES strings for chrome + beat copy |
| `assets/vhs_tape.glb` | Authored cassette mesh (tray / flight) |
| `assets/vhs_player.glb` | Vintage VHS player (Sketchfab CC-BY · Tejay21) |
| `vhs_reference*.png` | Mood board only — do not map to mesh |
| `assets/vhs_tape.glb` | Cassette mesh (procedural fallback) |
| `_shots/` | Dev screenshots — **excluded from GitHub Pages deploy** |

## Controls

- Scroll / touch → progress 0–1
- **Rewind / Rebobinar** → top
- **No audio / Sin audio · Hiss on** — procedural tape hiss + beat cues (muted by default; starts on user gesture)
- **← essay** → Exhibit A in the essay (`#exhibit-a`, preserves `?lang=`)
- **Archive beat** → link to full essay at Part I (`#part-i`, 37,829 posters)
- Mobile: pixel ratio ≤1.25, fewer particles, no shadow map; palette swatches fixed above HUD
- `prefers-reduced-motion`: no breathe / dry lag / no animated grain / no audio cues

## Teachable checklist

- [ ] Hero reads as VHS without reading the README
- [ ] Cover flat: no trapezoid / double perspective from box photos
- [ ] Scroll tells OCR → measure → open clearly
- [ ] Cassette appears **inside** on archive, not beside the hero shell
- [ ] Numbers live in DOM overlays / chips — not burned into the poster canvas
- [ ] Clean console (no errors)
- [ ] EN and ES copy both readable from essay language toggle

## Decisions

Stylized prop · thin bezel · procedural spine HALLOWEEN / 1978 · subtle wear on shell only (not artwork) · key/fill/rim lighting · contact shadow · dark floor · finale = soft lid open.
