# Corpus canónico

Criterio: **películas de terror en inglés, ya estrenadas, con póster, sin exclusiones, con año válido y sin filtro de adulto; se quitan animación, musicales y TV Movie.**

Fuente de verdad: `pipeline/data/canonical_ids.txt`, generado por `pipeline/build_corpus.py` a partir de metadatos TMDB vigentes (`pipeline/fetch_tmdb_details.py`). Todos los builders del sitio (`build_site.py`) filtran por este listado; los CSV crudos no se mutan.

Fecha de corte: `2026-10-08` · **n = 33,622** · años 1900–2026

## Embudo

| Paso | Quita | Quedan |
|---|---:|---:|
| Pósters con métricas |  | 63,126 |
| Ficha TMDB vigente | 933 | 62,193 |
| Género TMDB incluye Horror | 273 | 61,920 |
| Idioma original inglés | 24,062 | 37,858 |
| Estrenada (status Released y fecha ≤ hoy) | 528 | 37,330 |
| Sin filtro de adulto | 18 | 37,312 |
| Sin Animation / Music / TV Movie | 2,630 | 34,682 |
| Fuera de listas excluded_*.csv | 312 | 34,370 |
| Año válido | 32 | 34,338 |
| Con póster servible | 716 | 33,622 |

Cada película cuenta solo en el primer filtro que no cumple (`pipeline/data/qa/corpus/corpus_dropped.csv`).

## Listas de exclusión que aún quitaron películas

- `excluded_no_poster_available.csv`: 217
- `excluded_non_english.csv`: 64
- `excluded_music.csv`: 13
- `excluded_compilation.csv`: 9
- `excluded_tmdb_duplicate.csv`: 4
- `excluded_animation.csv`: 3
- `excluded_poster_md5_dup.csv`: 1
- `excluded_landscape.csv`: 1

## Reglas

- **Terror**: género TMDB actual incluye `Horror` (no basta etiqueta de comunidad).
- **Estrenada**: `status == Released` y `release_date` ≤ fecha de corte.
- **Año válido**: año del análisis entre 1900 y el año de corte (sin 9999).
- **Póster**: arte servible (path TMDB o asset local OMDb/actual) y fuera de `no_poster`.
- Regenerar: `python3 pipeline/fetch_tmdb_details.py && python3 pipeline/build_corpus.py && python3 pipeline/build_site.py`.
