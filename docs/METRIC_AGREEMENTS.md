# Acuerdos de métricas visuales

Una métrica, un dueño por superficie. No mezclar canales (ensayo / autopsy / master)
sin mapear taxonomías.

Identidad de póster: `pipeline/data/poster_src.csv` (`tmdb` / `tmdb_current` /
`omdb` / `no_poster`). Nunca escribir URLs Amazon en `poster_path` TMDB.
Los `no_poster` no se muestran en el sitio hasta que haya arte.

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

## Armas

| Uso | Fuente |
|-----|--------|
| Flag / análisis de presencia | Rek `rek_weapon ≥ 0.5` (o CLIP `clip_weapon` con el mismo umbral de familia) |
| Cajas OWL / DINO | Segundo voto en master / QA; **no** conteo del essay |
| Essay | Hoy no hay serie de armas; si se añade, una sola fuente |

OWL armas tiene FP ~58% en QA Nova: no contar cajas crudas.

## Criaturas / monstruos

| Superficie | Fuente canónica |
|------------|-----------------|
| Ensayo Part VII / décadas / explorer `creature` | **CLIP census** (`census.csv`), `score ≥ 0.5`; si no, `uncertain` |
| Tipo tipado / presencia fina | **JEV** reconciliado (`creature_present` / `creature_type`) |
| Cajas en autopsy | OWL **solo** si `box.label === census.label` y score ≥ umbral; si no, label CLIP sin cajas |

No usar OWL como presencia de monstruo. Al comparar CLIP ↔ JEV, mapear
taxonomías (`animal` colapsado en JEV vs `shark` / `spider` / … en CLIP).

## QA / gold

- Faces: YuNet floor documentado en el essay; gap YuNet=0∩Rek>0 es rescate UI, no essay.
  Nova `nova_faces` (de `qa_faces.csv`) se muestra en autopsy como nota QA; no entra a `resolveFaces` ni al essay.
- Creature census: CLIP es el dueño; Nova `nova_creature` (`qa_census.csv`) es nota QA en autopsy.
- Typography: CLIP register es el dueño; Nova `nova_typo` (`qa_typography.csv`) es nota QA.
- Title OCR: Nova `nova_title` / `nova_ocr` (`qa_title_ocr.csv`) es nota QA del título; no sustituye la caja de texto.
- Creature/weapon boxes: `pipeline/qa_creature_weapon_boxes.py` + veredictos Nova.
- JEV gold: `pipeline/data/qa/jev_pilot/gold.json` + `SUMMARY.md`.

## Cuando duden

1. ¿Qué superficie? (essay / autopsy / master)
2. ¿Cuál es el dueño en esta tabla?
3. ¿La otra fuente es rescate, segundo voto, o ruido?
