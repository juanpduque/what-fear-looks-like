# VHS Decompose — Halloween

Scroll-driven Three.js demo: clamshell VHS 3D de *Halloween* (1978) que gira, peela capas de análisis y **abre** (apertura / archivo) revelando métricas reales del corpus.

## Abrir

```bash
cd site && python3 -m http.server 8765
```

→ [http://localhost:8765/demos/poster-decompose/](http://localhost:8765/demos/poster-decompose/)

## Actos

| Acto | Progress | Qué pasa |
|---|---|---|
| **I · Objeto** | 0–12% | Hero ¾ — caja dominante, Media box art |
| **II · Frente** | 12–22% | Gira a frente; el sleeve es el trailer |
| **III · Capas** | 22–82% | Peel ordenado: OCR → faces → color → symmetry → blood → medium/mood |
| **IV · Archivo** | 82–100% | Tapa con bisagra abre; capas como ficha + cassette |

## Assets

- `vhs_reference.png` — Media Home Entertainment (cover principal si existe)
- `poster.jpg` — fallback
- `metrics.json` — beats + `raw` del corpus (TMDB 948)

## Controles

- Scroll / touch → progress 0–1
- **Rewind** → inicio
- **Sound off / Hiss on** — tape hiss (mute por defecto)
- Mobile: menos partículas, sin shadow map, pixel ratio capped
- `prefers-reduced-motion`: menos breathe / lag más seco

## Decisiones

Prop estilizado · clamshell grande · copy narrativo+cifra · final = apertura (no explode) · hiss opcional mute.
