# Community horror poster OCR set

Two products live in this project:

1. **Essay corpus** (`data/posters.csv`, ~37,829 rows here flagged `in_essay_corpus=1`): filtered EN horror used for *What Fear Looks Like*.
2. **Community set** (this manifest): TMDB horror posters with **Amazon Rekognition DetectText**, including titles outside the essay filters (other languages, shorts, etc.).

## File

- `community_manifest.csv` — **49,412** ids
- DetectText non-empty: **47,573**
- DetectText empty: **1,839**
- Overlap with essay corpus: **37,829**

## Sources

- Essay DetectText: `../poster_ocr_rek_text.csv`
- All-lang gap DetectText: `../poster_ocr_rek_text_alllang.csv`
- Metadata: `../horror_movies.csv`

## License / attribution

Posters remain © their rights holders; metadata via TMDB. OCR text is model output (Rekognition DetectText). Cite TMDB and this project if you redistribute derivatives.

## Optional enrichments

Textract / Comprehend for the all-lang gap land in `*_alllang.csv` beside the essay files when available.
