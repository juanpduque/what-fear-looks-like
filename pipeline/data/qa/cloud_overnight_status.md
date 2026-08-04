# Cloud Overnight Status — What Fear Looks Like

Agente: `bc-7ab52c54-12ba-4927-96a7-6091e58337f0`  
Región: `us-east-1` · Bucket workshop: `sagemaker-studio-a5572760`  
Fuente live sin credenciales: dashboard público `amaleli-website/wflike-jobs-dashboard`

---

## 2026-08-04T01:45:17Z — T0 arranque (live)

### Credenciales AWS
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`: **NO presentes** en el entorno Cloud Agent.
- No hay perfil `~/.aws`, ni IMDS/role, ni environment Cursor vinculado con secretos.
- AWS CLI instalado (`aws-cli/2.36.15`). `sts get-caller-identity` → `NoCredentials`.
- **Bloqueo:** no se puede DescribeInstances / S3 privado / IAM / Custom Labels API hasta que existan secretos.

### EC2 (vía dashboard público, poller Mac @ 01:44:01Z)
| Instance | Name | State | Type | IP |
|---|---|---|---|---|
| i-0b9777ca835a6d5ab | wflike-owlv2-backfill | running | c5.2xlarge | 54.152.164.51 |
| i-0c9df56ab11bf8b4b | wflike-community-72k | **gone** (ec2- @ 01:44) | — | — |

### Jobs
| Job | Status | Progress | Notas / Next |
|---|---|---|---|
| Community 72k | **DONE** | 100% phase=all | DONE marker; instancia detenida/terminada. Labels tuvo AccessDenied histórico (ok≈8923 err≈5727) luego pasó a detecttext (~15645 @ ~11.5/s) y cerró. |
| OWL CPU backfill | RUNNING? | creature=125/19263 (0.6%) | last_remote_ts=**00:44:45Z** (~1h stale). PROGRESS dice `device=cuda` en c5.2xlarge (sin GPU) — sospechoso. Dejar correr; sin AWS no se puede SSH/relaunch. |
| Custom Labels medium | DESCONOCIDO | project `wflike-medium-clf` v`v202608040132` | Sin credenciales → no DescribeProjectVersions. Objetivo: TRAINING_COMPLETED → compare F1 vs LogReg **0.5135**. |
| IMDb posters / features | DONE | 1239/609 · residual done | OK |
| Rekognition local enrich | DONE | ~49556 | OK |
| SigLIP / dashboard local | PENDING local | Mac sleep | 127.0.0.1:8765 + embeds mueren si Mac duerme |
| Overlap guard | ALERT (histórico) | — | AccessDenied DetectLabels en role; community ya cerró. IAM WflikeRekognitionDetect reportado como añadido — verificar con AWS cuando haya creds. |

### Acciones tomadas
1. Instalado AWS CLI.
2. Creada rama `cursor/overnight-aws-monitor-37f0`.
3. Loop de monitoreo cada ~30 min sobre dashboard público + reintento de credenciales.

### Next inmediato
- Reintentar secretos AWS cada ciclo.
- Si aparecen: EC2 describe, S3 PROGRESS reales, IAM DetectLabels, Custom Labels poll + `compare_f1`.
- OWL: si instancia muerta + S3 recuperable → relaunch CPU only (nunca g4dn).

---

## 2026-08-04T01:47:32Z — tick (ruta corregida)
### AWS: **sin credenciales** (solo dashboard público)
### Dashboard público (updated `2026-08-04T01:46:13Z`)
- summary: `{'running': 2, 'done': 4, 'alerts': 1, 'ec2_running': 1}`
| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | done | 100.0% all | status=done done_batch=None rate=None/s total_rows=None |
| OWL CPU/GPU backfill | running | 0.6% device=cuda | creature=125/19263 weapon=125 device=cuda |
| IMDb posters | done | 100.0% posters | IMDB_SELENIUM_DONE_20260804T003334Z | hits=1239 miss=609 |
| IMDb features | done | 100.0% features | wflike-imdb-features-residual: IMDB_SELENIUM_DONE_20260803T235149Z |
| Local rekognition enrich | done | 100.0% enrich | LISTO ok=0 err=3 elapsed=0.6m (0.00/s) main=49556 → data/qa/rekognition_community_enrich.csv |
| SigLIP / medium compare | running | 100.0% embed | pid=14846 vitl 311/311 |
| Overlap guard | alert | None% cleared | PAUSE_LABELS cleared after local enrich DONE; fresh skip uploaded; worker resumed labels | ALERT: AccessDeniedException  |
- ec2: `[{"instance_id": "i-0b9777ca835a6d5ab", "name": "wflike-owlv2-backfill", "state": "running", "type": "c5.2xlarge", "ip": "54.152.164.51", "profile": "sandbox"}]`

**OWL:** creature=125 last_ts=2026-08-04T00:44:45Z — SSH :22 abierto en 54.152.164.51; HTTP timeout. Progress stale desde 00:44Z.
**Nota:** monitor script path bug fixed (`pipeline/data/qa/...`).

---

## 2026-08-04T01:47:32Z — tick
### AWS: **sin credenciales** (solo dashboard público)
- sts error: `aws: [ERROR]: An error occurred (NoCredentials): Unable to locate credentials. You can configure credentials by running "aws login".`
### Dashboard público (updated `2026-08-04T01:46:13Z`)
- summary: `{'running': 2, 'done': 4, 'alerts': 1, 'ec2_running': 1}`
| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | done | 100.0% all | status=done done_batch=None rate=None/s total_rows=None |
| OWL CPU/GPU backfill | running | 0.6% device=cuda | creature=125/19263 weapon=125 device=cuda |
| IMDb posters | done | 100.0% posters | IMDB_SELENIUM_DONE_20260804T003334Z | hits=1239 miss=609 |
| IMDb features | done | 100.0% features | wflike-imdb-features-residual: IMDB_SELENIUM_DONE_20260803T235149Z |
| Local rekognition enrich | done | 100.0% enrich | LISTO ok=0 err=3 elapsed=0.6m (0.00/s) main=49556 → data/qa/rekognition_community_enrich.csv |
| SigLIP / medium compare | running | 100.0% embed | pid=14846 vitl 311/311 |
| Overlap guard | alert | None% cleared | PAUSE_LABELS cleared after local enrich DONE; fresh skip uploaded; worker resumed labels | ALERT: AccessDeniedException  |
- ec2: `[{"instance_id": "i-0b9777ca835a6d5ab", "name": "wflike-owlv2-backfill", "state": "running", "type": "c5.2xlarge", "ip": "54.152.164.51", "profile": "sandbox"}]`

**OWL check:** creature=125 weapon=125 last_ts=2026-08-04T00:44:45Z state=running — leave running unless instance dead.
**Community:** state=done phase=all (no relaunch; DONE expected).
**Local pending:** SigLIP embeds + dashboard 127.0.0.1:8765 mueren si Mac duerme.
