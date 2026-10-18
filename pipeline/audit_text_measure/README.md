# Text measure vs an OCR reader

The essay's "text-like coverage" (`text_area`) is the union of MSER glyph-candidate boxes, so it counts
texture as well as lettering. This checks it against EasyOCR (readable text only).

    python3 audit_text_measure/ocr_text_share.py audit_text_measure/results/ocr.jsonl 80

800 posters (80 per decade, 1930s-2020s, fixed seed), resized to 640 px wide; `ocr_area` is the share of the
sheet inside EasyOCR boxes with confidence >= 0.3. Resumable. Results (`results/ocr.jsonl`, 2026-10-17):

| decade | OCR area | MSER `text_area` |
|---|---|---|
| 1930s | 18.1% | 32.3% |
| 1950s | 15.8% | 35.6% |
| 1970s | 9.3% | 27.0% |
| 1990s | 11.5% | 24.9% |
| 2020s | 11.2% | 18.4% |

- Both fall to the 1970s (OCR roughly halves). After 1980 OCR stays flat at 9-12% while MSER keeps falling.
- Per-poster Spearman: 0.26 (area), 0.21 (tallest box), 0.17 (box count).
- MSER runs about twice the OCR level, so it is a trend, not a share of the sheet.
- The decade trend does not depend on the source image width (it holds inside each width band).
- The same poster also reads differently at different resolutions: Midsommar is 9% on the site's 342 px
  copy and 32% on the image the dataset measured.
