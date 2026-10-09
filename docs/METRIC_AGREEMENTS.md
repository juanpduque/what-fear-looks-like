# Acuerdos de métricas visuales

Una métrica, un dueño por superficie. No mezclar canales (ensayo / autopsy / master)
sin mapear taxonomías.

Identidad de póster: `pipeline/data/poster_src.csv` (`tmdb` / `tmdb_current` /
`omdb` / `no_poster`). Nunca escribir URLs Amazon en `poster_path` TMDB.
Los `no_poster` no se muestran en el sitio hasta que haya arte.
Traza de hoja: `pipeline/data/poster_bytes.csv`. El ensayo se une por
`role=measured`; las alts por `(id, file_path)`. `tmdb_hash` es el stem de
TMDB (`/xxx.jpg` → `xxx`) y sobrevive un 404 de la API. `sha256` es de los
bytes que medimos (local / S3 / w500). No sobrescribir un `file_path`
measured ya hashed si TMDB rota el primario — eso es drift, no identidad.
Regenerar: `python3 pipeline/hash_poster_bytes.py` (`--hash-local` / `--s3` /
`--fetch`).
Autopsy «otras hojas»: `site/data/poster_alts.json` = representantes de cluster
CLIP (`is_rep`) de `/movie/{id}/images`. Al seleccionar una alt, la mesa sigue
en esa hoja: paleta k-means, composición OpenCV, ViTPose, MSI-Net, YuNet,
OWL y título DetectText de `(id, file_path)`. No pintar cajas YuNet / OWL /
título de la medida. Rek DetectLabels es nota de esa ruta. Mapas alt:
`{id}_{stem}.png`, nunca `maps/{id}.png`. Sidecars: `poster_alts_pose.json`,
`poster_alts_sal.json`, `poster_alts_comp.json`, `poster_alts_rek.json`,
`poster_alts_faces.json`, `poster_alts_owl.json`, `poster_alts_text.json`.
La hoja canónica del ensayo sigue siendo `posters.csv` / explorer `p[2]`.
Paralelo Rek en peek: `poster_alts_rek.json` ← `rekognition_multi_variants.csv`
(DetectLabels + Image Properties sobre la ruta). No es el stack del ensayo.

## Rostros

| Superficie | Fuente canónica |
|------------|-----------------|
| Ensayo / `FACE_PTS` / explorer `n_faces` | **YuNet** (`faces_v2.csv`) |
| Autopsy (conteo + cajas) | `resolveFaces` en `site/src/autopsy/faces.js` |

Regla autopsy:

1. YuNet == Rek → ese conteo; cajas YuNet.
2. YuNet = 0, Rek > 0 → presencia Rek; cajas Rek si hay backfill.
3. Ambos > 0 y discrepan → **gana YuNet**; marcar desacuerdo.
4. Sin payload Rek → solo YuNet.

No regenerar series del essay con unión YuNet∪Rek sin cambiar el copy.

## Color

| Superficie | Fuente canónica |
|------------|-----------------|
| Ensayo Color River | **6 familias de matiz** (`band_red`…`band_dark`) |
| Autopsy Paleta | **k-means K=5** en CIELAB de esta hoja (`pal`) |
| Autopsy Familias de matiz | Las mismas 6 bandas del Río (`bands`) |
| Autopsy Oscuro | `dark_share` (L\*<20) — relacionado, no idéntico a `band_dark` |
| Autopsy mapa de calor | **MSI-Net** (`maps/{id}.png` medida; `{id}_{stem}.png` alt) |
| Autopsy centroide de balance | OpenCV StaticSaliencySpectralResidual (`comp.mx/my`) |

No mezclar las 5 muestras k-means con las 6 cuotas del Río. El Río no se alimenta de la paleta.
MSI-Net no es el centroide de balance ni una banda del Río.

## Medio (pintado / foto / compuesto)

| Superficie | Fuente canónica |
|------------|-----------------|
| Autopsy etiqueta de medio | **Rekognition Custom Labels** (`site/data/medium_cl.json` ← `infer_full.csv`) |
| Ensayo / explorer `painted` | **CLIP** `p_painted` (`medium.csv`) |
| Autopsy nota CLIP | `p_painted` continuo; no mueve el cajón si hay Custom Labels |

Si Custom Labels no cubre la hoja, autopsy usa el cajón CLIP (pintado ≥0.6 / foto ≤0.4 / mixto). No sobrescribir `medium.csv` ni las series del ensayo.

## Armas

| Uso | Fuente |
|-----|--------|
| Flag / análisis de presencia | Rek `rek_weapon ≥ 0.5` (o CLIP `clip_weapon` con el mismo umbral de familia) |
| Cajas OWL / DINO | Segundo voto / geometría autopsy; **no** conteo del essay |
| Autopsy cajas | OWL **solo** si score ≥ 0.3; presencia sigue siendo Rek (o CLIP familia) |
| Essay | Hoy no hay serie de armas; si se añade, una sola fuente |

OWL armas tiene FP ~58% en QA Nova: no contar cajas crudas.

## Criaturas / monstruos

| Superficie | Fuente canónica |
|------------|-----------------|
| Ensayo Part VII / décadas / explorer `creature` | **CLIP census** (`census.csv`), `score ≥ 0.5`; si no, `uncertain` |
| Tipo tipado / presencia fina | **JEV** reconciliado (`creature_present` / `creature_type`) |
| Autopsy etiqueta + cajas | CLIP + OWL **solo** si `box.label === census.label` y score ≥ umbral |
| Autopsy tipo tipado | JEV (`jev_creature` / `jev_present`); no mueve cajas OWL ni el essay |

No usar OWL como presencia de monstruo. Al comparar CLIP ↔ JEV, mapear
taxonomías (`animal` colapsado en JEV vs `shark` / `spider` / … en CLIP).

## QA / gold

- Faces: YuNet floor documentado en el essay; gap YuNet=0∩Rek>0 es rescate UI, no essay.
  Nova `nova_faces` (de `qa_faces.csv`) se muestra en autopsy como nota QA; no entra a `resolveFaces` ni al essay.
- Creature census: CLIP es el dueño; JEV `jev_creature` es el tipo tipado en autopsy (no essay).
  Nova `nova_creature` (`qa_census.csv`) es nota QA.
- Typography: CLIP register es el dueño; Nova `nova_typo` (`qa_typography.csv`) es nota QA.
- Title OCR: Nova `nova_title` / `nova_ocr` (`qa_title_ocr.csv`) es nota QA del título; no sustituye la caja de texto.
- Creature/weapon boxes: `pipeline/qa_creature_weapon_boxes.py` + veredictos Nova.
- JEV gold: `pipeline/data/qa/jev_pilot/gold.json` + `SUMMARY.md`.

## Cuando duden

1. ¿Qué superficie? (essay / autopsy / master)
2. ¿Cuál es el dueño en esta tabla?
3. ¿La otra fuente es rescate, segundo voto, o ruido?
