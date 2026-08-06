# OCR pilot v2 — resumen para Medium

## Caveats (español)

Este benchmark es **exploratorio**, no un paper. Usamos **n≈100** pósters de terror (muestra estratificada por década y text_area alto/bajo, corpus preferentemente en inglés, seed=42; n efectivo=100). La métrica principal es el solapamiento de tokens del título de catálogo en el OCR; la secundaria es fuzzy / «el título aparece» tras normalizar caracteres no alfanuméricos (útil cuando Florence pega tokens). Reportamos media ± desvío y un intervalo bootstrap 95% de la media de overlap. Costos de API son aproximados (~$0.0015/img para Google Vision / Rekognition); los VLM de Hugging Face se midieron en GPU EC2 y el costo es tiempo de instancia, no por imagen. No generalizar a otros géneros, idiomas o layouts sin una muestra más grande y un protocolo de anotación humana.

## Ranking (mean title_overlap, all rows)

| rank | model | ok_rate | mean overlap ± std | bootstrap 95% CI | mean fuzzy | title_hit | mean chars | mean latency (s) | cost |
|---:|:---|---:|---:|---:|---:|---:|---:|---:|:---|
| 1 | pixtral | 1.00 | 0.939 ± 0.229 | [0.890, 0.979] | 0.605 | 0.950 | 111 | 29.40 | ~$0.001–0.01/img (Bedrock Pixtral Large vision, rough) |
| 2 | gpt4o | 1.00 | 0.937 ± 0.232 | [0.888, 0.979] | 0.597 | 0.950 | 102 | 1.46 | ~$0.01–0.05/img (OpenAI gpt-4o vision detail=high; ~$2.50/1M in + $10/1M out; rough) |
| 3 | gemini-flash | 1.00 | 0.935 ± 0.235 | [0.889, 0.979] | 0.587 | 0.930 | 153 | 2.54 | ~$0.0005–0.002/img (Vertex gemini-2.5-flash vision, thinkingBudget=0; rough) |
| 4 | llama4-scout | 1.00 | 0.931 ± 0.247 | [0.883, 0.978] | 0.611 | 0.950 | 90 | 0.81 | ~$0.0005–0.005/img (Bedrock Llama 4 Scout vision, rough) |
| 5 | nova-2-lite | 1.00 | 0.916 ± 0.266 | [0.863, 0.963] | 0.593 | 0.940 | 185 | 2.10 | ~$0.0001–0.001/img (Bedrock Nova 2 Lite vision, rough; first-party credits) |
| 6 | qwen | 1.00 | 0.904 ± 0.277 | [0.849, 0.952] | 0.730 | 0.930 | 90 | 2.68 | HF self-host on GPU EC2 (g4dn time) |
| 7 | nova-lite | 1.00 | 0.895 ± 0.279 | [0.840, 0.945] | 0.577 | 0.910 | 267 | 1.39 | ~$0.0001–0.001/img (Bedrock Nova Lite vision, rough; first-party credits) |
| 8 | google | 1.00 | 0.889 ± 0.279 | [0.834, 0.937] | 0.596 | 0.840 | 89 | 0.34 | ~$0.0015/img (Vision TEXT_DETECTION, rough) |
| 9 | nova-pro | 1.00 | 0.875 ± 0.295 | [0.815, 0.930] | 0.581 | 0.880 | 181 | 1.39 | ~$0.001–0.01/img (Bedrock Nova Pro vision, rough; first-party credits) |
| 10 | rekognition | 1.00 | 0.849 ± 0.323 | [0.777, 0.907] | 0.578 | 0.800 | 100 | 0.71 | ~$0.0015/img (DetectText, rough) |
| 11 | deepseek | 1.00 | 0.806 ± 0.350 | [0.738, 0.874] | 0.584 | 0.810 | 141 | 3.06 | HF self-host on GPU EC2 (g4dn time) |
| 12 | paddle | 1.00 | 0.769 ± 0.384 | [0.691, 0.836] | 0.606 | 0.800 | 199 | 57.25 | HF self-host on GPU EC2 (g4dn time) |
| 13 | ppocr | 1.00 | 0.586 ± 0.440 | [0.503, 0.666] | 0.572 | 0.620 | 47 | 2.21 | local CPU/self-host (EC2 time if remote) |
| 14 | easyocr | 0.99 | 0.507 ± 0.434 | [0.414, 0.592] | 0.534 | 0.525 | 54 | 0.00 | cached corpus OCR (no incremental API cost) |
| 15 | florence | 1.00 | 0.374 ± 0.430 | [0.298, 0.457] | 0.612 | 0.850 | 70 | 2.59 | local/self-host (EC2 or laptop GPU/MPS time) |
| 16 | qianfan | 0.00 | 0.000 ± 0.000 | [0.000, 0.000] | nan | nan | nan | nan | HF self-host on GPU EC2 (g4dn time; larger VRAM risk) |
| 17 | got | 0.00 | 0.000 ± 0.000 | [0.000, 0.000] | nan | nan | nan | nan | HF self-host on GPU EC2 (g4dn time) |

## Notas de costo / latencia

- **API** (google, rekognition): ~$0.0015 por imagen; latencia de red dominante (~0.5–2 s típico).
- **Gemini Flash** (Vertex `gemini-2.5-flash`, thinkingBudget=0): VLM multimodal vía ADC; coste ≈ tokens imagen+prompt+salida (~$0.0005–0.002/img rough); latencia de red/modelo (~1–4 s típico).
- **GPT-4o** (OpenAI `gpt-4o`, vision `detail=high`, temperature=0): techo VLM de pago vía API; coste ≈ tokens imagen+prompt+salida (~$2.50/1M in + $10/1M out; ~$0.01–0.05/img rough con high detail); latencia de red/modelo (~1–5 s típico).
- **Claude** (Bedrock Sonnet 4.5/4.6, Converse + imagen): techo VLM de pago; costo ≈ tokens de entrada (imagen + prompt) + salida; mucho más caro que Vision/Rekognition por imagen. Requiere instrumento de pago válido en AWS Marketplace para Anthropic (INVALID_PAYMENT_INSTRUMENT).
- **Bedrock vision no-Anthropic** (nova-lite/pro, nova-2-lite, pixtral, llama4-scout, gemma3): Converse + imagen; Amazon Nova es first-party (créditos Bedrock aplican). Pixtral/Llama/Gemma son Marketplace pero en smoke no exigieron tarjeta como Claude.
- **EasyOCR**: reutilizado desde `poster_ocr.csv` (sin re-inferencia); latencia ≈ 0 en este piloto.
- **HF / self-host** (qwen, deepseek, paddle, qianfan, got, florence, ppocr): costo = tiempo de GPU/CPU (p. ej. g4dn.xlarge on-demand). Comparar latencia media por imagen en la tabla; OOM o load_error bajan ok_rate.

