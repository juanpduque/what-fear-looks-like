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

Precisión de las cajas OWL de criatura contra Nova (`pipeline/audit_creature_boxes.py`,
144,804 cajas juzgadas): crudas 21%; score ≥ 0.3, 30%; DINO misma etiqueta, 25%;
etiqueta = censo, 76%; score ≥ 0.3 + censo (lo que dibuja la autopsy), **80%**.
Comparar idiomas por criatura con el censo (`pipeline/world_creatures.py`), nunca con
conteos de cajas OWL: en los afiches no ingleses inflan la presencia (75–88% vs 62%).

## Imagen medida (registro por hash)

Las métricas se guardan por id de TMDB, pero la imagen de un id puede cambiar (TMDB cambia
la portada principal, `posters/{id}.jpg` se re-descarga). `pipeline/build_poster_images.py`
escribe `data/poster_images.csv` (local, fuera de git): sha256 + pHash del archivo en disco
y pHash de la ruta que muestra el sitio. Distancia pHash ≤ 10 = mismo arte.

Primera corrida (2026-10-13, 42,030 películas publicadas):

- Corpus en inglés: 32,938 de 33,058 comparables iguales (99.6%); 102 distintos (> 12).
- Mundo: 6,789 iguales; 1,375 distintos. En 1,316 de ellos el archivo local es la portada
  que TMDB muestra hoy, no la que muestra el sitio.
- Brillo recalculado en muestras de 40: corpus 40/40 medido sobre la imagen del sitio;
  mundo 31/40 sobre la del sitio y 9/40 sobre la de TMDB hoy (procedencia mezclada).

Antes de correr una métrica sobre `posters/`, cruzar con el registro: si `phash_dist` > 10,
el archivo no es la imagen publicada.

Restauración (2026-10-14): 1,544 archivos de `posters/` se reemplazaron por la imagen que
muestra el sitio (la vieja queda en `posters_tmdb_current/`). Después: corpus 33,057 iguales,
1 distinto (1441305, TMDB sirve otra imagen en la misma ruta); mundo 8,408 iguales (100%).

Re-medición de 1,440 afiches del mundo sobre la imagen restaurada:

- Color, caras, CLIP (embeddings, censo, tipografía, medio) y atributos: valores nuevos.
  Caras y CLIP viejos se habían medido sobre la portada equivocada (coseno CLIP viejo/nuevo
  ~0.73 en los 1,440, contra 0.98–1.0 en afiches sin cambio). Criaturas: 321 → 289.
- CLIP: usar los pesos openai de HF (`open_clip` ViT-B-32). `CLIP_CKPT=models/ViT-B-32.pt`
  no reproduce el censo guardado (86.9% contra 99.9% en 60 afiches de control).
- Segmentación (ADE / MINC / CLIP): mismo código, pero no se reproduce en otra máquina. La
  original corrió en GPU en AWS (`aws/seg_chain.sh`, CUDA, `pip install -U` sin versiones
  fijas); en CPU del Mac cambia la clase ganadora de algunos parches de la cuadrícula 2×2. En
  40 afiches del corpus sin cambio de imagen: CLIP cambia en 57% (|Δ| medio 0.038, término
  principal igual en 75%), ADE en 85% (0.006), MINC en 32% (0.008). El embedding CLIP de la
  imagen completa tampoco se reproduce (coseno mediano 0.988), con pesos HF ni con el ckpt
  local. Medir sobre la portada equivocada pesa más: en los 1,440, CLIP cambia en 95% (|Δ|
  medio 0.113, término principal igual en 36%). Re-medición 2026-10-16: los 1,440 pasan a la
  segmentación en CPU del Mac sobre la imagen restaurada (repetible: 32 de 32 idénticos).
  Quedan medidos en otra máquina que el resto. `segmentation_decade.json` (serie del ensayo)
  no se regeneró: el ensayo no cambia. En el sitio solo se ven en las 44 fichas
  restauradas de `world_lookup.js` (`sem`: sangre, arma...); cambian 43.
- Cajas OWLv2 de criaturas del mundo (`qa/creature_boxes_world.json`): ya estaban medidas
  sobre la imagen del sitio (10 de 10 coinciden, IoU 0.86–0.98 en la caja principal).
- Cajas de armas (`weapon_boxes.json`): venían de la imagen equivocada. En las 44 fichas
  restauradas de `world_lookup.js` se vaciaron; las detecciones nuevas están en
  `qa/weapon_boxes_world_restored_unjudged.json`. Nova Pro las juzgó el 2026-10-17: 31 cajas
  en 16 afiches, 14 correctas, 16 falsos positivos (letras del título leídas como flechas,
  dedos, personas) y 1 dudosa; veredictos en `qa/weapon_boxes_world_restored_nova_judged.csv`
  y añadidos a `qa/qa_creature_weapon_boxes.csv`. Solo se publican las 14 correctas (6 fichas:
  6312, 10226, 96001, 185341, 464737, 499195). Los otros 1,396 afiches no se publican con
  cajas de armas: desde que todas las fichas del gráfico del mundo se pueden abrir
  (`data/world/{lang}.js`), `build_world_lookup.py` descarta las cajas cuyo sha256 en
  `metric_images.csv` no es el del archivo de hoy (81 de los 4,598).
  Los 565 afiches con `weapon_boxes` desactualizado en `qa/metric_images_stale.csv` se
  re-detectaron el 2026-10-17 con OWLv2 sobre la imagen de hoy (Mac CPU, 10-17 s por afiche,
  `owlv2_creature_boxes.py --with-weapons`) y Nova Pro juzgó las 731 cajas nuevas: 253 correctas,
  471 falsos positivos, 7 dudosas (`qa/weapon_boxes_world_stale565_nova_judged.csv`; detecciones en
  `qa/weapon_boxes_world_stale565_owlv2_cpu.json`). Solo se publican las correctas (159 afiches, 55
  de ellos en el gráfico del mundo, con 87 cajas). Control de reproducibilidad previo, CPU del Mac
  frente a lo medido en AWS sobre las mismas imágenes (10 afiches con cajas): 16 de 21 cajas
  reproducidas, IoU medio 0.885, diferencia media de confianza 0.022; los fallos están pegados al
  umbral 0.2 y hay un cambio de etiqueta (hammer a baseball_bat). `build_world_lookup.py` ya no
  descarta ninguna caja por medirse sobre otra imagen (antes 81).

Registro por métrica (2026-10-16): `pipeline/metric_images.py` escribe
`data/metric_images.csv` (local, fuera de git): una fila por película publicada y una
columna sha256 por métrica (color, caras, embeddings CLIP, censo, tipografía, medio,
atributos, segmentación, Rekognition, cajas de criaturas, cajas de armas). Vacío = la
métrica no tiene fila para esa película. Se sembró con `--seed` asumiendo que cada métrica
se midió sobre el archivo de hoy, salvo lo que dice el manifiesto de la restauración: en los
1,440 del mundo, segmentación y cajas de armas quedan con el sha256 del archivo viejo (las
cajas de armas en 565 de ellos; las 44 fichas vaciadas no tienen). Esa suposición se revisó
en muestras, no película por película. Después la segmentación de los 1,440 se re-midió
(#55) y el registro se actualizó con `record`: quedan solo las 565 cajas de armas. 2 películas del corpus (264880, 1007963) no tienen
archivo en `posters/` ni métricas.

Sin argumentos, el script vuelve a calcular el hash de `posters/` (unos 25 minutos en el disco
USB) y escribe `data/qa/metric_images_stale.csv` con cada métrica medida sobre otro archivo.
`reanalyze_poster_ids.py` actualiza el registro de las métricas que vuelve a medir. Un script
que mida una métrica debe llamar `metric_images.record(métrica, ids)` al terminar.

Otros géneros (Parte VII, `export_genre_comparison.py`), revisado 2026-10-16 en muestras de
300 por género: el archivo de `posters/` es la portada registrada en
`community_{género}/tmdb_{género}_analysis_meta.csv` en 296–299 de 300 (pHash ≤ 10), y el
negro recalculado en 40 por género da el valor guardado exacto (diferencia 0).

## QA / gold

- Faces: YuNet floor documentado en el essay; gap YuNet=0∩Rek>0 es rescate UI, no essay.
  Nova `nova_faces` (de `qa_faces.csv`) se muestra en autopsy como nota QA; no entra a `resolveFaces` ni al essay.
- Creature census: CLIP es el dueño; JEV `jev_creature` es el tipo tipado en autopsy (no essay).
  Nova `nova_creature` (`qa_census.csv`) es nota QA.
- Typography: CLIP register es el dueño; Nova `nova_typo` (`qa_typography.csv`) es nota QA.
- Title OCR: Nova `nova_title` / `nova_ocr` (`qa_title_ocr.csv`) es nota QA del título; no sustituye la caja de texto.
- Creature/weapon boxes: `pipeline/qa_creature_weapon_boxes.py` + veredictos Nova.
- Título en japonés / chino / coreano / tailandés: PaddleOCR (`pipeline/paddleocr_world_titles.py`,
  `world_title_size.py`); Rekognition DetectText solo lee alfabeto latino. Revisión a mano: 37/40.
- JEV gold: `pipeline/data/qa/jev_pilot/gold.json` + `SUMMARY.md`.

## Cuando duden

1. ¿Qué superficie? (essay / autopsy / master)
2. ¿Cuál es el dueño en esta tabla?
3. ¿La otra fuente es rescate, segundo voto, o ruido?
