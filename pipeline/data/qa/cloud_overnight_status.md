# Cloud Overnight Status — What Fear Looks Like

Agente: `bc-7a2db836-fe3f-4015-93d3-fb4d6f1cd3cb`  
Región: `<region>` · Bucket workshop: `sagemaker-studio-a5572760`  
Cuenta STS: `567596065542` · Rol: `WSParticipantRole/Participant`

---

## 2026-08-04T01:57:00Z — T0 arranque (AWS OK)

### Credenciales AWS
| Check | Resultado |
|---|---|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` | **Presentes** |
| `aws sts get-caller-identity` | **OK** — `arn:aws:sts::567596065542:assumed-role/WSParticipantRole/Participant` |
| Cursor Environment vinculado | `null` (secrets inyectados igual en este run nuevo) |

### Tabla live

| Job | Status | Progress | Notas / Next |
|---|---|---|---|
| Community 72k | **DONE** | 100% phase=all | `DONE_20260804T014326Z`. S3: rekognition **15642** rows, detecttext **15645** rows, log `ALL PHASES DONE`. EC2 `i-0c9df56ab11bf8b4b` **terminated** — sin billing idle. |
| OWL CPU backfill | **RUNNING sano** | **2250/19263** (~11.7%) | `i-0b9777ca835a6d5ab` c5.2xlarge **running**. PROGRESS real S3: `device=cpu` (no cuda) @ 01:58:21Z. ~3.0s/img → ETA ~14h. Checkpoints S3 cada ~3 min. **No relaunch.** |
| Custom Labels medium | **TRAINING_COMPLETED** | F1=**0.6454** vs LogReg **0.5135** (Δ+0.132) | Escrito `pipeline/data/qa/medium_custom_labels/compare_f1.json`. Billable ~3322s. |
| IMDb posters / features | DONE | — | Sin acción overnight. |

### EC2

| Instance | Name | State | Type | Acción |
|---|---|---|---|---|
| i-0b9777ca835a6d5ab | wflike-owlv2-backfill | running | c5.2xlarge | Dejar correr (CPU sano) |
| i-0c9df56ab11bf8b4b | wflike-community-72k | **terminated** | c5.xlarge | Ya apagada; Community DONE |

### Investigación OWL (anomalía 125/cuda)

1. **Dashboard público stale / bucket incorrecto:** el poller Mac leía `s3://aof-owlv2-102516364259/.../PROGRESS` → stuck en `creature=125 device=cuda` @ 00:44Z.
2. **S3 workshop (verdad):** `s3://sagemaker-studio-a5572760/wflike-owlv2-backfill/results/PROGRESS` → `creature_delta=2175 device=cpu ts=01:55:17Z`.
3. Log real: `owlv2_backfill_chain start (CPU)`, `torch …+cpu cuda False`, ritmo estable 3.0s/img, sync periódico vivo (consola EC2 hasta 2200+).
4. `ENV` en S3 aún dice `DEVICE=cuda` (metadata de launch); el worker CPU **ignora** eso y reporta `device=cpu` en PROGRESS.
5. Script en S3 `code/aws/owlv2_backfill_chain.sh` es variante GPU hardcodeada; la instancia ya arrancó con cadena CPU — **no tocar**. Resume: deltas en S3 (`creature_boxes_delta.json` / `weapon_boxes.json`) permiten retomar si hiciera falta.

### Acciones tomadas
1. Verificado STS + instalado AWS CLI.
2. Confirmado Community DONE + artefactos S3 + EC2 community terminated.
3. Confirmado OWL vivo/CPU; **no** terminate, **no** relaunch GPU.
4. Custom Labels COMPLETED (F1 0.645 > LogReg 0.5135) → `compare_f1.json`.
5. Loop overnight cada ~25–35 min → append a este archivo.

### Next
- Poll OWL PROGRESS cada ciclo (Custom Labels ya cerrado).
- Si OWL se estanca >12 min sin avance → investigar; relaunch CPU only con resume desde S3 deltas.
- No mass-download posters; no force-push; no matar jobs sanos.

---

## 2026-08-04T01:59:53Z — Custom Labels COMPLETED

| Métrica | Valor |
|---|---|
| Version | `v202608040132` |
| Status | TRAINING_COMPLETED |
| Custom Labels F1 | **0.645415** |
| LogReg F1 (brief) | 0.5135 |
| Δ F1 | **+0.131915** (beats LogReg) |
| Artefacto | `pipeline/data/qa/medium_custom_labels/compare_f1.json` |

---

## 2026-08-04T01:59:49Z — tick

### AWS: **OK** (`arn:aws:sts::567596065542:assumed-role/WSParticipantRole/Participant`)

| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | UNKNOWN | ? | EC2=terminated · `{   "phase": "all",   "status": "done",   "n_ids": 68011,   "ts": "2026-08-04T01:42:49Z",   "bucket": "sagemaker-studio-` |
| OWL CPU backfill | RUNNING | 2250/19263 (11.7%) device=cpu | ts=2026-08-04T01:58:21Z · EC2 `i-0b9777ca835a6d5ab` running c5.2xlarge · ETA~14.2h · sano |
| Custom Labels v202608040132 | TRAINING_COMPLETED | F1=0.6454153060913086 | The model is ready to run. · wrote pipeline/data/qa/medium_custom_labels/compare_f1.json |

**Acción:** wrote pipeline/data/qa/medium_custom_labels/compare_f1.json


---

## 2026-08-04T02:02:03Z — tick

### AWS: **OK** (`arn:aws:sts::567596065542:assumed-role/WSParticipantRole/Participant`)

| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | DONE | 100% | EC2=terminated · `{   "phase": "all",   "status": "done",   "n_ids": 68011,   "ts": "2026-08-04T01:42:49Z",   "bucket": "sagemaker-studio-` |
| OWL CPU backfill | RUNNING | 2325/19263 (12.1%) device=cpu | ts=2026-08-04T02:01:26Z · EC2 `i-0b9777ca835a6d5ab` running c5.2xlarge · ETA~14.1h · sano |
| Custom Labels v202608040132 | TRAINING_COMPLETED | F1=0.6454153060913086 | The model is ready to run. · compare_f1.json already present |


---

## 2026-08-04T02:02:49Z — tick

### AWS: **OK** (`arn:aws:sts::567596065542:assumed-role/WSParticipantRole/Participant`)

| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | DONE | 100% | EC2=terminated · `{   "phase": "all",   "status": "done",   "n_ids": 68011,   "ts": "2026-08-04T01:42:49Z",   "bucket": "sagemaker-studio-` |
| OWL CPU backfill | RUNNING | 2325/19263 (12.1%) device=cpu | ts=2026-08-04T02:01:26Z · EC2 `i-0b9777ca835a6d5ab` running c5.2xlarge · ETA~14.1h · sano |
| Custom Labels v202608040132 | TRAINING_COMPLETED | F1=0.6454153060913086 | The model is ready to run. · compare_f1.json already present |


---

## 2026-08-04T02:39:46Z — tick

### AWS: **OK** (`arn:aws:sts::567596065542:assumed-role/WSParticipantRole/Participant`)

| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | DONE | 100% | EC2=terminated · `{   "phase": "all",   "status": "done",   "n_ids": 68011,   "ts": "2026-08-04T01:42:49Z",   "bucket": "sagemaker-studio-` |
| OWL CPU backfill | RUNNING | 3075/19263 (16.0%) device=cpu | ts=2026-08-04T02:38:26Z · EC2 `i-0b9777ca835a6d5ab` running c5.2xlarge · ETA~13.5h · sano |
| Custom Labels v202608040132 | TRAINING_COMPLETED | F1=0.6454153060913086 | The model is ready to run. · compare_f1.json already present |


---

## 2026-08-04T03:14:22Z — tick

### AWS: **OK** (`arn:aws:sts::567596065542:assumed-role/WSParticipantRole/Participant`)

| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | DONE | 100% | EC2=unknown · `{   "phase": "all",   "status": "done",   "n_ids": 68011,   "ts": "2026-08-04T01:42:49Z",   "bucket": "sagemaker-studio-` |
| OWL CPU backfill | RUNNING | 3775/19263 (19.6%) device=cpu | ts=2026-08-04T03:12:17Z · EC2 `i-0b9777ca835a6d5ab` running c5.2xlarge · ETA~12.9h · sano |
| Custom Labels v202608040132 | TRAINING_COMPLETED | F1=0.6454153060913086 | The model is ready to run. · compare_f1.json already present |


---

## 2026-08-04T03:45:36Z — tick

### AWS: **OK** (`arn:aws:sts::567596065542:assumed-role/WSParticipantRole/Participant`)

| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | DONE | 100% | EC2=unknown · `{   "phase": "all",   "status": "done",   "n_ids": 68011,   "ts": "2026-08-04T01:42:49Z",   "bucket": "sagemaker-studio-` |
| OWL CPU backfill | RUNNING | 4400/19263 (22.8%) device=cpu | ts=2026-08-04T03:43:03Z · EC2 `i-0b9777ca835a6d5ab` running c5.2xlarge · ETA~12.4h · sano |
| Custom Labels v202608040132 | TRAINING_COMPLETED | F1=0.6454153060913086 | The model is ready to run. · compare_f1.json already present |


---

## 2026-08-04T04:10:26Z — tick

### AWS: **OK** (`arn:aws:sts::567596065542:assumed-role/WSParticipantRole/Participant`)

| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | DONE | 100% | EC2=unknown · `{   "phase": "all",   "status": "done",   "n_ids": 68011,   "ts": "2026-08-04T01:42:49Z",   "bucket": "sagemaker-studio-` |
| OWL CPU backfill | RUNNING | 4875/19263 (25.3%) device=cpu | ts=2026-08-04T04:07:40Z · EC2 `i-0b9777ca835a6d5ab` running c5.2xlarge · ETA~12.0h · sano |
| Custom Labels v202608040132 | TRAINING_COMPLETED | F1=0.6454153060913086 | The model is ready to run. · compare_f1.json already present |


---

## 2026-08-04T04:27:39Z — tick

### AWS: **OK** (`arn:aws:sts::567596065542:assumed-role/WSParticipantRole/Participant`)

| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | DONE | 100% | EC2=unknown · `{   "phase": "all",   "status": "done",   "n_ids": 68011,   "ts": "2026-08-04T01:42:49Z",   "bucket": "sagemaker-studio-` |
| OWL CPU backfill | RUNNING | 5250/19263 (27.3%) device=cpu | ts=2026-08-04T04:26:08Z · EC2 `i-0b9777ca835a6d5ab` running c5.2xlarge · ETA~11.7h · sano |
| Custom Labels v202608040132 | TRAINING_COMPLETED | F1=0.6454153060913086 | The model is ready to run. · compare_f1.json already present |


---

## 2026-08-04T04:27:44Z — tick

### AWS: **OK** (`arn:aws:sts::567596065542:assumed-role/WSParticipantRole/Participant`)

| Job | Status | Progress | Detail |
|---|---|---|---|
| Community 72k | DONE | 100% | EC2=unknown · `{   "phase": "all",   "status": "done",   "n_ids": 68011,   "ts": "2026-08-04T01:42:49Z",   "bucket": "sagemaker-studio-` |
| OWL CPU backfill | RUNNING | 5250/19263 (27.3%) device=cpu | ts=2026-08-04T04:26:08Z · EC2 `i-0b9777ca835a6d5ab` running c5.2xlarge · ETA~11.7h · sano |
| Custom Labels v202608040132 | TRAINING_COMPLETED | F1=0.6454153060913086 | The model is ready to run. · compare_f1.json already present |

