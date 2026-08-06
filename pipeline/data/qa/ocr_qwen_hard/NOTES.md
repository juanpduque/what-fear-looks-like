# OCR Qwen hard mini-pilot notes

- **Hard set (regenerated 2026-07-31):** **9** ids
- Base definition: ocr_pilot_v2 `model=qwen` with **stored** `title_overlap_score < 1` (historical hard12)
- QC:
  - Title overrides: `data/qa/ocr_qa_title_overrides.csv`
  - Exclusions: `data/qa/ocr_qa_exclude_ids.csv`
  - Dropped if rescored overlap ≥ 1 after title fix (metadata false hard)
- Dropped rows: `hard_qc_dropped.csv`
- Poster sources: 6 true homolog / rest w342 (see `poster_sources.csv` where present)
- Models: qwen2b-hard = Qwen2-VL-2B-Instruct; qwen7b-hard = Qwen2-VL-7B-Instruct @ 4bit

## Kept ids

- `10283` — Friday the 13th Part VIII: Jason Takes Manhattan (qwen rescored=0.625)
- `26921` — The Mystery of the Mary Celeste (qwen rescored=0.2)
- `28265` — Lovesick: Sick Love (qwen rescored=0.3333)
- `233194` — 8 Butterflies (qwen rescored=0.0)
- `286452` — Varsity Blood (qwen rescored=0.0)
- `653537` — Whispers (qwen rescored=0.0)
- `1405670` — xOxExFx (qwen rescored=0.0)
- `1483743` — up here, disappear (qwen rescored=0.6667)
- `1578643` — Cymophane (qwen rescored=0.0)

## Dropped

- `77399` — Incense for the Damned: rescored_perfect_after_title_fix
- `940187` — THE INQUISTION: rescored_perfect_after_title_fix
- `1015482` — Kiss of the Serpent: exclude: Non-English poster (German Todeskuss der Schlange); EN-poster OCR eval only
