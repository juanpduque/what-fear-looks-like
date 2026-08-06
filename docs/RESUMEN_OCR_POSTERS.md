# Resumen de avance — OCR, techos VLM y pósters

**Proyecto:** What Fear Looks Like / Cómo se ve el miedo  
**Fecha del resumen:** 29–30 jul 2026  
**Repo:** `what-fear-looks-like`

> **Artículo paso a paso (máxima calidad de título + tablas/gráficos):**  
> [`ARTICULO_OCR_TITULOS_POSTERS.md`](ARTICULO_OCR_TITULOS_POSTERS.md)  
> Benchmark cerrado: `pipeline/data/qa/ocr_article/` · primary **Pixtral** full-frame (`winner.json`).

---

## 1. Objetivo general

Evaluar OCR / visión sobre pósters de terror para el artículo (Medium) y preparar un corpus de imágenes de **mejor calidad y tamaño homogéneo** para trabajo a escala (~14k del set de QA filtrado).

---

## 2. Benchmark OCR piloto v2 (n=100)

### Qué se hizo

- Muestra estratificada **n=100** (década × text_area, seed 42) en `pipeline/data/qa/ocr_pilot_v2/`.
- Baselines locales/API: easyocr, florence, ppocr, **google** Vision, **rekognition**.
- VLMs self-host en EC2 GPU (`g4dn`): **qwen** (Qwen2-VL-**2B**), deepseek, paddle; qianfan/got fallaron al cargar.
- Techos cloud:
  - **Bedrock** (créditos AWS): nova-lite, nova-pro, **pixtral**, **llama4-scout** (~$0.64 total n=100).
  - **Claude** en Bedrock: bloqueado (`INVALID_PAYMENT_INSTRUMENT` / Marketplace).
  - **Gemini Flash** (Vertex / GCP): 100/100 ok.
  - **GPT-4o** (OpenAI, detail=high): 100/100 ok (~$0.14).
- Resultados fusionados (sidecars Gemini/GPT + Bedrock) → `results.csv` + `summary.md`.

### Ranking (mean title_overlap)

| # | Modelo | Overlap | Notas |
|---|--------|---------|--------|
| 1 | **pixtral** (Bedrock) | **0.939** | Mejor; lento (~29 s/img, throttle) |
| 2 | **gpt4o** | **0.937** | Empate práctico; ~$0.14 / 100 |
| 3 | **gemini-flash** | **0.935** | Muy buen valor en GCP |
| 4 | **llama4-scout** | **0.931** | Rápido (~0.8 s) |
| 5 | qwen (2B self-host) | 0.904 | Open-weight; mejorable con 7B / w780 |
| 6 | nova-lite | 0.895 | Barato first-party Bedrock |
| 7 | google Vision | 0.889 | Rápido / ~$0.0015/img |
| … | deepseek, paddle, ppocr, easyocr, florence | ↓ | florence: overlap bajo pero title_hit alto |

Artefactos: `pipeline/data/qa/ocr_pilot_v2/` (`summary.md`, `summary.csv`, `results.csv`).

### Estimación a ~18k pósters (orden de magnitud)

| Opción | ≈ coste 18k |
|--------|-------------|
| Gemini Flash | ~$9–36 |
| GPT-4o | ~$25 (medido en piloto) |
| Google Vision | ~$27 |
| Qwen self-host | ~$10 GPU-h |
| Pixtral | caro en wall-clock (throttle) |

---

## 3. Set de QA filtrado (corpus review)

- Lista oficial: `pipeline/data/qa/corpus_filter_qa_ids.csv` → **14 384** ids  
  (EN + filtros comedy/music/anim/TV/votes/poster, etc.; UI `site/corpus-filter-qa.html`).
- No es “18k exactos”: el número vivo del QA es **~14.4k**.

---

## 4. Pósters originales (TMDB `/original`) → S3

### Qué se hizo

- Script: `pipeline/fetch_posters_original_qa.py`
- Fuente: mismo `poster_path` TMDB, tamaño **`/original`** (no w342).
- Local: `pipeline/data/posters_original/`
- S3: `s3://aof-owlv2-102516364259/posters_original/`

### Resultado

| Métrica | Valor |
|---------|--------|
| Descargados / subidos | **14 383 / 14 384** |
| Miss | 1 (HTTP 502 TMDB) |
| Disco / S3 | **~5.5 GB** |

### Distribución de anchos (review)

| Width | n |
|-------|--:|
| 500–699 | 3 523 (24.5%) |
| 700–999 | 2 236 |
| 1000–1499 | 5 165 |
| 1500+ | 3 459 |

- p50 ≈ **1000×1500**
- Informe: `pipeline/data/qa/posters_original_size_summary.md`

Conclusión: “original” en TMDB a menudo **no** es 2k; muchas másters son 500–750 px.

---

## 5. Real-ESRGAN (GPU) — en curso

### Qué se decidió

- Upscale **solo** width &lt; 1000 (**5 759** ids).
- Modelo: RealESRGAN_x2plus, **x2**, tile 400.
- Runtime: EC2 **g4dn.xlarge** (Tesla T4).
- Fix técnico: `basicsr` no compila en Python 3.13 del AMI → pipeline con **spandrel**.

### Estado (al cerrar este resumen)

- Instancia: `i-0d33118b8a50c4d81` (running)
- Progreso aprox.: **~300 / 5 759**
- Salida: `s3://…/posters_original_up/` (sync periódico)
- ETA restante: **~2.5–3.5 h**

Scripts: `upscale_posters_realesrgan.py`, `aws/stage_poster_upscale.sh`, `aws/launch_poster_upscale.sh`, `aws/poster_upscale_chain.sh`.

---

## 6. Homologación 1000×1500 letterbox — programada

### Decisión

Al terminar ESRGAN:

1. Preferir `posters_original_up/{id}.jpg` si existe; si no, `posters_original/{id}.jpg`
2. **Contain + letterbox** a **1000×1500** (barras negras, sin crop agresivo)
3. Escribir `posters_homolog/` y subir a  
   `s3://aof-owlv2-102516364259/posters_homolog/`

Scripts: `homolog_posters_letterbox.py`, `aws/wait_homolog_after_upscale.sh` (waiter en background esperando `DONE`).

---

## 7. Hallazgos útiles para el ensayo / Medium

1. **Primary de máxima calidad de título: Pixtral** full-frame (0.939 n=100; **0.601** hard12) — ver artículo.
2. **Cuatro techos casi empatados** en n=100 (~0.93–0.94): Pixtral, GPT-4o, Gemini Flash, Llama 4 Scout; en **hard**, Pixtral se separa.
3. **Mejor OSS hard:** Kimi-VL-A3B (~0.48) > Qwen-7B 4bit (~0.43) > PP-OCRv6 (~0.39).
4. **Crop de texto empeora** VLM; homolog letterbox solo +0.02 en n=35.
5. **Google Vision** sigue siendo el dulce spot API clásico (~0.89 n=100; competitivo en hard).
6. Para escala por $/latencia: **Gemini Flash** o **Llama 4 Scout**; Pixtral gana calidad hard pero throttle ~29 s/img.
7. Detalle narrativo + figuras: [`ARTICULO_OCR_TITULOS_POSTERS.md`](ARTICULO_OCR_TITULOS_POSTERS.md).

---

## 8. Pendiente inmediato

- [x] Real-ESRGAN width&lt;1000 → `posters_original_up/`
- [x] Letterbox 1000×1500 → `posters_homolog/`
- [x] Artículo OCR + `ocr_article/` ladders/figuras (primary Pixtral)
- [ ] (Opcional) Roll-out Pixtral/Gemini al corpus QA 14 384
- [ ] (Opcional) Reintentar el miss TMDB `211222`
- [ ] (Opcional) Claude cuando haya payment instrument en Marketplace
- [ ] (Opcional) Rotar API key de OpenAI expuesta en chat

---

## 9. Rutas S3 clave

| Prefijo | Contenido |
|---------|-----------|
| `s3://aof-owlv2-102516364259/posters_original/` | TMDB original QA (14 383) |
| `s3://aof-owlv2-102516364259/posters_original_up/` | Real-ESRGAN x2 (width&lt;1000) |
| `s3://aof-owlv2-102516364259/posters_homolog/` | 1000×1500 letterbox (~14 383) |
| `s3://aof-owlv2-102516364259/ocr_pilot_v2/` | Benchmark OCR n=100 |
| `s3://aof-owlv2-102516364259/ocr_qwen_hard/` | Hard n=12 Qwen 2B/7B |
| `s3://aof-owlv2-102516364259/ocr_kimi_hard/` | Hard n=12 Kimi-VL |
| `s3://aof-owlv2-102516364259/ocr_ppocrv6_hard/` | Hard n=12 PP-OCRv6 |
| `s3://aof-owlv2-102516364259/poster_upscale/` | Código + logs del job ESRGAN |
| Local `pipeline/data/qa/ocr_article/` | Ladders + figuras del artículo |
