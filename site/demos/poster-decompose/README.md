# VHS Decompose — Halloween (enseñable)

Scroll-driven Three.js: clamshell VHS 3D de *Halloween* (1978). El sleeve es **arte plano del corpus** (`poster.jpg`). Las fotos de cajas físicas (`vhs_reference*.png`) son mood board — **nunca** albedo del cover.

## Abrir

```bash
cd site && python3 -m http.server 8765
```

→ [http://localhost:8765/demos/poster-decompose/](http://localhost:8765/demos/poster-decompose/)

(Sirve desde `site/` para que módulos ES + assets relativos funcionen.)

## 4 beats (holds largos)

| Beat | Progress | Qué pasa |
|---|---|---|
| **Hero** | 0–22% | Caja cerrada ¾ — se lee como VHS (spine + face) |
| **Read** | 22–45% | Frente + OCR bbox · HALLOWEEN conf 0.98 |
| **Measure** | 45–72% | Peel ordenado: faces 0 → 87% dark → symmetry 0.93 |
| **Archive** | 72–100% | Tapa abre suave (`lidPivot`); cassette dentro + ficha; knife 0.95 |

Sin explode caótico. Una capa dominante a la vez.

## Assets

| Archivo | Uso |
|---|---|
| `poster.jpg` | **Cover albedo** (aspect medido al cargar, ~500×750) |
| `vhs_reference.png` | Mood board only — no mapear al mesh |
| `vhs_reference_anniversary.png` | Mood board only |
| `metrics.json` | 4 beats + `raw` del corpus (TMDB 948) |
| `captures/` | Screenshots de aceptación (opcional) |

## Controles

- Scroll / touch → progress 0–1
- **Rewind** → inicio
- **Sound off / Hiss on** — tape hiss (mute por defecto)
- Mobile: pixel ratio ≤1.25, menos partículas, sin shadow map
- `prefers-reduced-motion`: sin breathe / lag seco / sin grain animado

## Checklist enseñable

- [ ] Hero ¾ se lee como VHS sin leer el README
- [ ] Cover flat: sin trapecio / doble perspectiva de foto de caja
- [ ] Scroll cuenta OCR → measure → open con claridad
- [ ] Cassette aparece **dentro** al abrir, no al lado en el hero
- [ ] Números viven en DOM overlays / chip — no quemados gigantes en el canvas del poster
- [ ] Consola limpia (sin errores)

## Decisiones

Prop estilizado · bezel fino · spine procedural HALLOWEEN / 1978 · wear sutil solo en shell (no en artwork) · lighting key/fill/rim · contact shadow · suelo oscuro · final = apertura suave.
