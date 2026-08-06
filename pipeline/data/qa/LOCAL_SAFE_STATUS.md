# LOCAL_SAFE_STATUS — 2026-08-04T02:09Z

Trabajo **solo local-safe**. No se tocó EC2, OWL, community-72k, DetectLabels masivo, ni PAUSE_LABELS. Sin GPU.

## 1. Medium backbone compare (SigLIP / ViT-L / DINOv2)

| Item | Estado |
|------|--------|
| Proceso | **activo** `pid=14846` **PPID=1** — `run_medium_backbone_pipeline.sh` |
| Log | `pipeline/data/qa/medium_backbone_compare/pipeline_embed.log` |
| `compare_f1.json` | **aún no** (pipeline en curso) |

Progreso al momento del chequeo:

- **ViT-L / OpenCLIP** — hecho (`openclip_vitl14_openai.npz`, n=421)
- **siglip-so400m** — falló (API transformers 5.x / `BaseModelOutputWithPooling`); el script hizo fallback
- **siglip-base** — **hecho** (`siglip_base.npz`, n=421)
- **dinov2-base** — **en curso** (cargando / embebiendo, CPU)
- Luego: dinov2-large (best-effort) → `train_medium_backbone_compare.py --from-cache` → `compare_f1.json`

Fix local (para reintentos futuros de so400m): parche en `pipeline/embed_medium_backbone.py` para extraer features vía mapping/index API de ModelOutput (transformers≥5). El proceso actual ya pasó so400m; no hace falta reiniciar.

## 2. Jobs dashboard poller

- **Vivo** `pid=16871` — `jobs_dashboard_poller.py --interval 45`
- `start_jobs_dashboard.sh` → *Poller already running*
- Sync S3 read-only OK (último: `sync=ok` ~02:08Z)
- Parent = Cursor extension-host (no PPID=1); no se reinició para no interrumpir sync

## 3. Custom Labels (wflike-medium-clf / v202608040132)

- Poller previo (`aws_custom_labels_medium.py --poll --wait`) **murió** por `ExpiredTokenException`
- Último estado conocido en logs/JSON: **TRAINING_IN_PROGRESS**
- Intento read-only `DescribeProjectVersions`: **bloqueado** — token `AWS_PROFILE=sandbox` expirado
- **No** se llamó `CreateProjectVersion`
- Nota append: `medium_custom_labels/run.log` + `describe_poll.jsonl`

Acción humana: refrescar credenciales sandbox y relanzar solo `--poll --wait`.

## 4. IMDb Selenium pull

- Marcador local presente: `IMDB_SELENIUM_DONE_20260804T003334Z`
- CSVs + ~217 posters bajo `pipeline/data/imdb_selenium_s3_pull/`
- Re-`pull_imdb_selenium.sh` **no ejecutado**: mismo `ExpiredToken` en sandbox

## Forbidden (respetado)

- Sin terminate/stop/run-instances EC2  
- Sin relaunch OWL / community-72k  
- Sin suite masiva DetectLabels / Rekognition Labels nueva  
- Sin clear/set PAUSE_LABELS  
- Sin GPU  

## Siguiente (local)

1. Esperar fin del pipeline → `pipeline/data/qa/medium_backbone_compare/compare_f1.json`
2. Tras SSO/creds sandbox: poll CL + opcional `pull_imdb_selenium.sh`
