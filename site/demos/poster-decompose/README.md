# Poster Decompose — Fase A (VHS box)

Demo scrollytelling: una caja VHS 3D de *Halloween* (1978) se descompone al scroll en capas de análisis (oscuridad, rojo, paleta, composición).

## Ver localmente

```bash
# desde la raíz del repo
python3 -m http.server 8080 --directory site
# abrir http://localhost:8080/demos/poster-decompose/
```

O con cualquier static server que sirva `site/`.

## Texturas

| Archivo | Uso |
|---|---|
| `poster.jpg` | Stand-in actual: póster teatral TMDB (`948`). |
| `vhs_reference.png` | **Pendiente.** Portada Media Home Entertainment (caja completa con footer MEDIA / créditos). Si existe, la demo la usa como textura frontal y **apaga** el packaging procedural (evita doble branding). |

### Cómo añadir el box art Media

1. Copia tu referencia (p. ej. `assets/s-l1200-*.png` o el PNG que enviaste) a:
   `site/demos/poster-decompose/vhs_reference.png`
2. Recarga la demo — detecta el archivo automáticamente.
3. Con Media cover activo: spine/back se simplifican (sin footer MEDIA procedural ni créditos inventados encima del arte real).

## Pulido Fase A (esta rama)

- Preferencia `vhs_reference.png` → `poster.jpg`.
- Sin doble packaging cuando hay cover Media.
- Edge wear: cartón blanco asomando por el negro/azul de la caja.
- Beats de scroll + capas de análisis (datos id 948).
- CSS 3D (sin WebGL / sin GPU local) — liviano para no saturar el laptop.
- **No** Phase B (apertura física, peel shaders, jobs AWS).

## Datos

Métricas congeladas de Halloween (TMDB 948) usadas en las capas:

- L\* ≈ 8.1, dark 87%, red 16%
- Paleta: `#070101` `#370f0e` `#711910` `#c53c0d` `#d5bda2`
- Neg space 66%, diagonal 0.20, faces 0
