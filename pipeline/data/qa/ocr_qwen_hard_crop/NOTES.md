# OCR Qwen hard-crop mini-pilot notes

- Sample: same 12 hard ids as `ocr_qwen_hard` (title_overlap < 1 in ocr_pilot_v2 qwen)
- Pipeline: open-source text det → crop (~10% margin) → Qwen2-VL on crops
- Det: PaddleOCR / TextDetection failed on this AMI (OneDNN PIR + empty boxes from classic predict path). **Surya DetectionPredictor** used successfully.
- Crop coverage: **11/12 real crops**, 1 full-image fallback (`653537` — no boxes)
- Models: `qwen2b-crop` = Qwen2-VL-2B-Instruct; `qwen7b-crop` = Qwen2-VL-7B-Instruct @ 4bit
- Instance: `i-05a5ca4eaa3a24836` / `100.55.132.111` (g4dn.xlarge, 200GB gp3) — terminated after DONE
- Headline: crop did **not** beat full-poster hard run (7B mean 0.34 crop vs 0.43 hard; win/tie/loss vs hard 0/9/3)
