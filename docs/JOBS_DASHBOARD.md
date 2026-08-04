# Jobs Dashboard (GitHub Pages + S3 live data)

Vista HTML de los jobs del pipeline (Community 72k, OWL, IMDb, Rekognition, SigLIP, EC2, …) con auto-refresh.

## URLs

| Qué | URL |
|---|---|
| **GitHub Pages (remoto)** | https://juanpduque.github.io/what-fear-looks-like/jobs-dashboard/ |
| **Datos live (S3 público)** | https://amaleli-website.s3.amazonaws.com/wflike-jobs-dashboard/status.json |
| **Eventos** | https://amaleli-website.s3.amazonaws.com/wflike-jobs-dashboard/events.log |
| **Local HTTP** | `http://127.0.0.1:8765/` (tras `start_jobs_dashboard.sh`) |
| **file://** | `site/jobs-dashboard/index.html` (usa `./status.json` o `?src=` a S3) |

Archivo privado de respaldo (no usable desde el browser):  
`s3://sagemaker-studio-a5572760/wflike-jobs-dashboard/`

## Activar / verificar GitHub Pages

Pages **ya está configurado** en este repo (`build_type: workflow`, fuente `site/` vía `.github/workflows/pages.yml`).

Si en otro clone no estuviera activo:

1. GitHub → repo **what-fear-looks-like** → **Settings** → **Pages**
2. **Source**: *GitHub Actions* (no “Deploy from a branch” con `/docs`, salvo que cambies el workflow)
3. Push a `main` de algo bajo `site/**` (p. ej. `site/jobs-dashboard/index.html`) dispara el deploy
4. Abre: https://juanpduque.github.io/what-fear-looks-like/jobs-dashboard/

El HTML en Pages **no** lleva el JSON en el repo: lo pide por HTTPS al bucket público en cada refresh (30–60s).

## Arrancar el poller (Mac)

```bash
bash pipeline/aws/start_jobs_dashboard.sh
# o:
python3 pipeline/jobs_dashboard_poller.py --interval 45
python3 pipeline/jobs_dashboard_poller.py --once   # un tick
```

El poller escribe:

- `pipeline/data/qa/jobs_dashboard/status.json`
- `pipeline/data/qa/jobs_dashboard/events.log`
- espejo en `site/jobs-dashboard/status.json` (local; no commitear)
- sync S3 cada ciclo → sandbox (privado) + `amaleli-website` (público, CORS `*`)

Requisitos AWS: perfiles `sandbox` (lectura jobs + archive) y `default` (subida pública).

## Si el Mac está apagado

Mueve el poller a un EC2 mínimo / cron:

```bash
# en la instancia (con AWS CLI + perfiles o roles)
*/1 * * * * cd /path/to/repo/pipeline && python3 jobs_dashboard_poller.py --once >> data/qa/jobs_dashboard/cron.log 2>&1
```

Mientras el poller no corra, Pages seguirá mostrando el último `status.json` en S3 (badge **stale**).

## Override de fuente

En el móvil/otro device:  
`https://juanpduque.github.io/what-fear-looks-like/jobs-dashboard/?src=https://amaleli-website.s3.amazonaws.com/wflike-jobs-dashboard/status.json`

## Nota de seguridad

`status.json` es progreso de jobs (conteos, ids de instancia, fases). No incluye secrets ni API keys. No subas `.env` ni credenciales al prefix público.
