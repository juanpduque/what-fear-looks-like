# OCR PP-OCRv6 medium hard mini-pilot

- Sample: same 12 hard ids as `ocr_qwen_hard` (title_overlap < 1 in ocr_pilot_v2 qwen)
- Posters: reused `_ocr_qwen_hard_stage/posters` + `poster_sources.csv` (6 homolog / 6 w342; no fake letterbox)
- Model: **PP-OCRv6 medium** classic det+rec via `paddleocr==3.7` / PaddleX
  - `text_detection_model_name=PP-OCRv6_medium_det`
  - `text_recognition_model_name=PP-OCRv6_medium_rec`
  - Result tag: `ppocrv6-medium` (NOT PaddleOCR-VL)
- Where: **local Mac ARM CPU** (`pilot_ppocrv6_hard.py --device cpu`)
- Workaround that worked: `FLAGS_use_mkldnn=0` + `FLAGS_onednn=0` (same OneDNN PIR issue class as hard_crop AMI). No EC2 needed for n=12.
- Latency: ~6.5s mean / poster on CPU after ~14s model load; 12/12 ok

## title_overlap (n=12)

| model | mean | median |
|-------|------|--------|
| qwen7b-hard | 0.434 | 0.333 |
| **ppocrv6-medium** | **0.392** | **0.167** |
| qwen7b-crop | 0.340 | 0.000 |
| qwen2b-hard | 0.299 | 0.000 |
| qwen2b-crop | 0.243 | 0.000 |
| qwen (v2) | 0.204 | 0.000 |

Win/tie/loss vs baselines (ppocrv6-medium):
- vs qwen7b-hard: **1/9/2**
- vs qwen2b-hard: **3/7/2**
- vs qwen-v2: **4/7/1**
- vs qwen7b-crop: **1/10/1**

## Verdict

**Not worth scaling as primary OCR** on this hard set: mean below qwen7b-hard, only one clear win (1483743), two losses (10283, 28265). Useful as a cheap CPU baseline / possible ensemble first-pass, not a 7B replacement.
