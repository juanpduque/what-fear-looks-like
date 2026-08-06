# Inventario cloud AWS — What Fear Looks Like

**Fecha inventario:** 2026-08-04 (~11:22Z dashboard / fuentes locales)  
**Perfil AWS:** `sandbox` → **ExpiredToken** (sin DescribeInstances / sin pull S3 privado).  
**Fuentes:** dashboard público [`status.json`](https://amaleli-website.s3.amazonaws.com/wflike-jobs-dashboard/status.json), caches locales `pipeline/data/qa/jobs_dashboard/`, CSVs QA, logs.

> Convención: **analizados** = filas/IDs con resultado útil en artefacto local o último contador remoto observado. **Restantes** = objetivo − analizados (o fallidos pendientes). Resultados EC2 72k **aún no bajados** al Mac.

---

## Tabla maestra (español)

| # | Job | Dónde | Estado | Analizados (n) | Restantes / fallidos | Artefactos |
|---|-----|-------|--------|----------------|----------------------|------------|
| 1 | **Community 72k** (enum→download→DetectLabels→DetectText) | EC2 `c5.xlarge` `i-0c9df56ab11bf8b4b` → S3 sandbox | **DONE** (instancia terminada ~01:44Z) | Enum **68 011** IDs; Labels pico **ok≈8 923** + **err≈5 727** (AccessDenied); DetectText **≈15 645** (último ok=15 124 err=1, luego DONE) | Labels: ~5 727 AccessDenied + ~992 no vistos en último batch (~15 642 todo); DetectText: ~0–520 residuales (job marcó done). **Sin merge local** | S3 `s3://sagemaker-studio-a5572760/wflike-community-72k/` (`results/PROGRESS.json`, `rekognition_community_72k.csv`, `detecttext_community_72k.csv`, `DONE`); local: `qa/community_72k_rekognition_status.json`, `qa/jobs_dashboard/cache/community_PROGRESS.json` |
| 2 | **Rekognition enrich local** (~11.7k) | **Mac → API AWS** Rekognition (no EC2) | **DONE** | **ok=11 677** (+ sidecar 11 727 filas); merge → `rekognition.csv` **49 556** | **err=3** `ImageTooLargeException` (ids 1311988, 1381225, 1388574) | `pipeline/data/qa/rekognition_community_enrich.csv`, `.log`; main `pipeline/data/rekognition.csv` |
| 3 | **DetectText community anterior** (~49k) | **Mac → API AWS** DetectText (+ Textract paralelo) | **DONE** | DetectText único **49 462** (37 892 + 11 583 alllang); Textract **37 829** + alllang **11 583** | DetectText err=6 en set principal; coverage essay+community casi completa en disco | `poster_ocr_rek_text.csv`, `poster_ocr_rek_text_alllang.csv`, `poster_ocr_textract*.csv` |
| 4 | **IMDb Selenium posters** | EC2 `t3.large` → S3 | **DONE** | **hits=1 239** | **miss=609** (pull local miss CSV=582; ~217 JPG en pull parcial) | S3 `…/wflike-imdb-selenium/`; local `imdb_selenium_s3_pull/imdb_poster_hits.csv`, `IMDB_SELENIUM_DONE` |
| 5 | **IMDb Selenium features** | EC2 residual → S3 | **DONE** | **hits=19** | **miss=426** | S3 `…/wflike-imdb-features-residual/`; local `imdb_selenium_features_*.csv` |
| 6 | **OWL-ViT backfill** creature+weapon | EC2 GPU `g4dn.xlarge` cuenta AOF (`aof-owlv2-…`); antes CPU sandbox | **PARTIAL / ESTANCADO** (PROGRESS viejo; EC2 ausente en poll) | **125 / 19 263** creature+weapon | **19 138** restantes; boxes existentes previos **18 716** | S3 `s3://aof-owlv2-102516364259/wflike-owlv2-backfill/results/PROGRESS`; local `qa/owlv2_backfill/launch.json`, `creature_boxes.json` (18 716) |
| 7 | **Custom Labels** medium | Managed Rekognition Custom Labels (sandbox) | **TRAINING_IN_PROGRESS** (último conocido; poll bloqueado por token) | Gold **421** (train 315 / test 106) subidos; training `v202608040132` iniciado 01:32Z | Estado final desconocido sin SSO | `qa/medium_custom_labels/custom_labels_run.json`, manifests S3 `wflike-custom-labels/medium/` |
| 8 | **Multi-variant Rekognition** | **Mac → API AWS** | **DONE** | **10 883** filas / **5 054** films (variants 10 577 + primary 306) | — | `qa/rekognition_multi_variants.csv` |
| 9 | **Nova enrich** | **Mac local** + **Bedrock AWS** | **DONE** | **37 829** ok | errors CSV históricos ~5 074 (reintentos previos); corpus essay cubierto | `qa/nova_enrich/nova_enrich.csv`, `progress.json`, `json/` |
| 10 | Overlap guard / PAUSE_LABELS | Mac + S3 flags | **ALERT** (histórico) | skip_labels final **49 556** | Alert: AccessDenied DetectLabels en rol EC2 | `qa/rekognition_overlap_guard.json` |
| 11 | SigLIP / medium backbone compare | Mac local (no Rekognition cloud) | **DONE** | **420** embeds + `compare_f1.json` | — | `qa/medium_backbone_compare/` |

---

## Detalle por job

### 1. Community 72k (EC2)

| Fase | Estado | Números |
|------|--------|---------|
| Enumerate TMDB horror | DONE | **n_ids=68 011** (no 72 531 estimado) |
| Download posters → S3 | DONE (implícito; job llegó a labels/text) | Posters en `s3://…/posters/` (conteo exacto no legible sin AWS) |
| DetectLabels (+IP/Mod/Faces) | PARTIAL → job siguió a DetectText | todo≈**15 642**; pico **ok≈8 923 / err≈5 727** (`AccessDeniedException` rol `wflike-ec2-role`); done_batch≈14 650 |
| DetectText | DONE (aprox.) | todo≈**15 645**; último visto ok=15 124 err=1; luego `status=done phase=all` |
| Pull → Mac | **NO** | `stale_cache` / ExpiredToken |

**Instancia:** `i-0c9df56ab11bf8b4b` · **DONE marker** ~2026-08-04T01:42:49Z · EC2 gone ~01:44Z.

### 2. Enrich local (~11.7k) — AWS API desde Mac

- Corrió en Mac contra Rekognition; **no** es el worker EC2.
- Log: `LISTO ok=11677 err=3` (~67.7 min, ~2.87/s) → merge en `rekognition.csv` = **49 556**.
- Sidecar `rekognition_community_enrich.csv`: **11 727** filas (⊂ main).
- 3 fallos definitivos por imagen >10 000 px.

### 3. DetectText community ~49k (previo al 72k EC2)

| Artefacto | Filas | Notas |
|-----------|-------|-------|
| `poster_ocr_rek_text.csv` | 37 892 | essay-ish; ok 37 886 / err 6 |
| `poster_ocr_rek_text_alllang.csv` | 11 583 | community-only alllang |
| **Unión DetectText** | **49 462** | essay 37 842 + community_only 11 583 cubiertos |
| Textract (AWS) | 37 829 + 11 583 alllang | paralelo OCR |

Esto es el DetectText “community earlier”; el DetectText del job 72k EC2 (~15.6k) es **adicional en S3**, aún no unido.

### 4–5. IMDb Selenium (EC2)

| Modo | ok | err/miss | Prefijo S3 |
|------|-----|----------|------------|
| Posters | 1 239 | 609 | `wflike-imdb-selenium` |
| Features residual | 19 | 426 | `wflike-imdb-features-residual` |

Pull local incompleto (~217 JPG); necesita SSO + `pull_imdb_selenium.sh`.

### 6. OWL backfill

| | |
|--|--|
| Target | **19 263** (creature + weapon queries) |
| Progreso último | **125 / 19 263** (0.6%) · `device=cuda` · ts **2026-08-04T00:44:45Z** |
| Restantes | **19 138** |
| Existentes pre-backfill | `creature_boxes.json` **18 716** |
| Cuentas | Sandbox sin GPU quota → relanzado en AOF `102516364259` / `g4dn.xlarge` |
| Estado real | Dashboard dice `running`, pero EC2 ya no aparece y PROGRESS no avanza → tratar como **estancado** hasta verificar con creds |

### 7. Custom Labels

- Proyecto `wflike-medium-clf` / versión `v202608040132`
- Status último: **TRAINING_IN_PROGRESS** (01:32Z); poll murió por ExpiredToken (~02:00Z)
- Baseline local logreg macro-F1 ≈ **0.513**
- Acción: `aws sso login --profile sandbox` + `python pipeline/aws_custom_labels_medium.py --poll --wait`

### 8. Multi-variant Rekognition

- `rekognition_multi_variants.csv`: **10 883** análisis / **5 054** films
- AWS DetectLabels desde Mac sobre variantes de poster

### 9. Nova (Bedrock)

- Proceso local; cómputo LLM en **Bedrock**
- **37 829** filas ok = cobertura essay; `progress.json` marca done

---

## TOTALES (cuantitativos)

### Posters / corpus

| Métrica | n |
|---------|---|
| JPG en disco `pipeline/data/posters/*.jpg` | **49 559** |
| `horror_movies.csv` IDs | 49 960 |
| Essay `attributes.csv` | 37 842 |
| Community manifest | 49 412 (essay 37 829 + community_only 11 583) |
| TMDB enum 72k (real) | **68 011** |
| Gap enum 72k − JPG locales | **≈18 452** (posters viven sobre todo en S3 72k) |
| JPG sin Labels | **3** (los ImageTooLarge) |
| JPG sin DetectText local | **97** |

### Unique con Labels

| Ámbito | n | Nota |
|--------|---|------|
| Local `rekognition.csv` (essay + community + extras) | **49 556** | fuente de verdad Mac |
| Essay | 37 842 / 37 842 | 100% |
| Community_only (manifest) | 11 580 / 11 583 | 3 ImageTooLarge |
| Multi-variant (filas, no unique film) | 10 883 | adicional |
| EC2 72k Labels ok (S3, no merge) | **≈8 923** | + AccessDenied ≈5 727 |
| **Unique Labels si se mergea EC2 ok** (estimado) | **≈58 479** | 49 556+8 923 si disjuntos |
| Restante Labels vs enum 68 011 (post-merge est.) | **≈9 532** + reintentos AccessDenied | requiere IAM + relaunch/pull |

### Unique con DetectText

| Ámbito | n |
|--------|---|
| Local unión Rek DetectText | **49 462** |
| EC2 72k DetectText (S3, no merge) | **≈15 645** |
| **Estimado post-merge** | **≈65 107** |
| Restante vs enum 68 011 | **≈2 904** (+ ids sin poster_path) |

### Otros AWS

| | n |
|--|---|
| Nova (Bedrock) essay | 37 829 DONE |
| OWL backfill | 125 / 19 263 |
| IMDb poster hits | 1 239 |
| Custom Labels training | en curso (estado incierto) |

---

## Qué queda (priorizado)

1. **SSO sandbox** — desbloquear Describe*, pull S3, poll Custom Labels.
2. **IAM DetectLabels** en `wflike-ec2-role` — sin esto no se recuperan ~5.7k AccessDenied ni el gap Labels del 72k.
3. **`pull_community_72k.sh`** — bajar `rekognition_community_72k.csv` + `detecttext_community_72k.csv` y mergear a main (~+8.9k Labels, ~+15.6k DetectText).
4. **OWL backfill** — verificar si GPU AOF sigue viva; si no, relanzar desde checkpoint (19 138 restantes).
5. **Custom Labels** — `--poll --wait`; si falló training, revisar/re-lanzar.
6. **3 ImageTooLarge** — resize y re-DetectLabels.
7. **IMDb miss** — 609 posters / 426 features; política de reintento o aceptar hueco.
8. **~18k posters** del enum 68k que no están en disco local — ya en S3 72k; decidir si se materializan localmente.
9. **JPG sin DetectText local (~97)** + residual DetectText 72k tras merge.

---

## Notas de confianza

- Conteos EC2 Labels/DetectText del 72k vienen del **events log** del dashboard (no del CSV S3). Tras pull, recalcular uniques.
- OWL “running” en status público es **stale** (PROGRESS 00:44Z; `ec2_running=0`).
- No hay carpeta `cloud_overnight` en el repo; staging Nova: `qa/nova_enrich/cloud_stage/`.
- Dashboard actualizado: `2026-08-04T11:22:48Z` · `community_72k.error=stale_cache` por token.


---

## Update 2026-08-04 — Medium Custom Labels + OWL

- **Custom Labels** (`wflike-medium-clf`): **TRAINING_COMPLETED** — F1 **0.645** (fuente: `cloud_agent_report_2026-08-04`). Ver `medium_custom_labels/compare_f1.json`.
- Ranking Medium (macro F1): **Custom Labels 0.645** > **SigLIP base 0.590** > **LogReg 0.5135**.
- **OWL** en `i-0b9777ca835a6d5ab`: ~**8900 / 19263** (~46%).
- Sin llamadas AWS locales si token SSO expirado (`ExpiredToken`).
