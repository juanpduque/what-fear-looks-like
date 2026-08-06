# Medium package — examples + cost precision

Assets: `pipeline/data/qa/ocr_pilot_v2/medium_examples/`
- `{id}.jpg` posters
- `extracts.json` full model texts

Metric note for the article: `title_overlap` = token overlap of catalog title vs OCR string (casefold). Glued tokens like `8BUTTERFLIES` score **0** even if the letters are “there.”

---

## 1) Side-by-side examples (n=100)

### Example A — Artistic / glued typography  
**TMDB id:** `233194` · **Correct title:** *8 Butterflies* (2010)  
**Why it fits:** Title is designed as a single stylized word-unit (`8BUTTERFLIES`). Classic OCR often keeps it glued → overlap 0. VLMs that insert a space get overlap 1.0.

| Model | Overlap | Extract (title-relevant) |
|-------|--------:|--------------------------|
| Google Vision | **0.00** | `… 8BUTTERFLIES …` |
| Rekognition | **0.00** | `… 8BUTTERFLIES …` |
| EasyOCR | **0.00** | `LOSE YOUR MIND 8BU, oatoun…` |
| Qwen 2B | **0.00** | `8BUTTERFLIES` |
| Llama 4 Scout | **0.00** | `8BUTTERFLIES` |
| **GPT-4o** | **1.00** | `8 BUTTERFLIES` |
| **Gemini Flash** | **1.00** | `8 BUTTERFLIES` |
| **Pixtral** | **1.00** | `8 BUTTERFLIES` |

Poster: `medium_examples/233194.jpg`

Caveat for Medium: GPT/Gemini/Pixtral also **hallucinate credits** (different cast/crew each). They win the *title* metric; they are not faithful full-poster transcripts.

---

### Example B — Distorted / high-coverage title lettering (horror only)  
**TMDB id:** `1022479` · **Correct title:** *You're Melting!* (2022) · genre: **Horror**  
**Why it fits:** Large warped display type (`text_area` 0.64). Google almost gets it but drops the apostrophe and ends in `MELTINE` → overlap **0**. VLMs recover `YOU'RE MELTING`.

| Model | Overlap | Extract (title-relevant) |
|-------|--------:|--------------------------|
| EasyOCR | **0.00** | `Yaial ar` |
| Google Vision | **0.00** | `YOURE MELTINE` |
| Rekognition | **1.00** | `YOU'RE … MELTING` *(scrambled word order with credits)* |
| **GPT-4o** | **1.00** | `YOU'RE MELTING` |
| **Gemini Flash** | **1.00** | `YOU'RE MELTING!` |
| **Pixtral** | **1.00** | `YOU'RE MELTING` |
| Llama 4 Scout | **1.00** | `You're Melting` |
| Qwen 2B | **1.00** | `YOU'RE MELTING` |

Poster: `medium_examples/1022479.jpg`

Replaced *Gildersleeve's Ghost* (1944): comedy one-sheet that leaked into the sample (`genre_names` was null, so the Comedy filter never caught it).

---

### Example C — Dark / low-contrast + stylized stacking  
**TMDB id:** `931049` · **Correct title:** *Beware the Woods* (2022)  
**Brightness** in corpus color metrics: **23.7** (dark).  
**Why it fits:** Dark forest poster; stacked BE SCARED / BE AFRAID / BEWARE THE WOODS. Google mangles to `BEWAREN` / `THE WOODEN` (overlap 0.33). VLMs get the full title.

| Model | Overlap | Extract (title-relevant) |
|-------|--------:|--------------------------|
| EasyOCR | **0.33** | `BEWARA THE Woons…` |
| Google Vision | **0.33** | `BEWAREN` / `THE WOODEN` |
| Rekognition | **1.00** | `BEWARE` / `THE WOODS` *(classic OCR can win here)* |
| **GPT-4o / Gemini / Pixtral / Qwen / Llama** | **1.00** | `BEWARE THE WOODS` |

Poster: `medium_examples/931049.jpg`

Honest note: this is **not** “all OCR fails.” Rekognition succeeds. Best Medium framing: *Google fails; VLMs succeed; traditional OCR is inconsistent across engines.*

---

### Vice versa (OCR wins, LLMs fail)?
In the n=100 pilot, with models `{google, rekognition, easyocr, ppocr}` vs `{gpt4o, gemini-flash, pixtral, llama4-scout, qwen}`:

**No cases** where classic-OCR max ≥ 0.75 and VLM max &lt; 0.45.

So for the piece: VLMs dominate hard title failures; you do **not** have a clean “OCR saved us, LLM hallucinated the title away” counterexample on this sample. You *do* have VLMs inventing fake credits (Example A) — use that as the vice-versa on **faithfulness**, not title hit.

---

## 2) Costs at ~18,000 posters — be precise

Scale factor used below: **18,000 / 100 = 180×** the n=100 pilot.  
(Your QA set is actually **14,384**; multiply by **143.84** if you chart that instead.)

| Model | What we actually know | Per image | @ 18k | Label for chart |
|-------|----------------------|-----------|------:|-----------------|
| **GPT-4o** | **Measured** from `gpt4o_usage.csv`: 42,350 in + 3,370 out tokens @ $2.50/$10 per 1M | **$0.001396** | **~$25.12** | **Measured** |
| **Google Vision** | List price used in notes (~$1.50 / 1k images TEXT_DETECTION) | ~$0.0015 | **~$27** | **List-price estimate** |
| **Gemini Flash** | **Not metered from billing.** COST_NOTES heuristic from Vertex pricing × image tokens on w342 | **$0.0005–0.002** | **$9–36** | **Estimate only** (not an invoice) |
| **Pixtral Large** | **Not metered.** Bedrock list often cited **$2 / 1M in + $6 / 1M out**. Pilot had **no token usage log**. Prior internal heuristic ~$0.42 / 100 ⇒ ~$0.0042/img | Rough **$0.002–0.01** | Rough **$36–180** (wide) | **Estimate only** |
| **Pixtral “high”?** | In our notes, **“high” = latency/ops**, not proven $ cost: mean **~29.4 s/img**, ~0.82 GPU-API-hours wall for n=100, heavy throttling | — | Wall-clock nightmare at 18k (~**147 hours** serial) | Say **high latency / poor scale**, cost = estimate |

### Chart wording that stays honest

> **GPT-4o (~$25 / 18k):** extrapolated from measured OpenAI token usage on the n=100 w342 pilot.  
> **Gemini Flash ($9–36 / 18k):** price-model estimate, **not** confirmed against GCP billing export.  
> **Pixtral:** treat cost as **uncertain estimate**; call out **~30 s/image + throttling** as the real reason not to scale it. Do **not** print a single Pixtral dollar number as fact.

### If you need one Pixtral dollar line
Use a **banded** figure, e.g. **~$40–80 / 18k (estimated)** with footnote: *assumes ~1–2k input tokens/image at Bedrock $2/$6 per 1M; we did not log tokens.*  
Or omit Pixtral from the cost chart and keep it only on the accuracy/latency chart.

---

## 3) Suggested Medium figure captions (English)

1. *8 Butterflies (2010): Google keeps the title glued as `8BUTTERFLIES` (overlap 0). GPT-4o / Gemini / Pixtral insert the space and score 1.0 — while inventing contradictory credit blocks.*  
2. *You're Melting! (2022): Google reads `YOURE MELTINE` (overlap 0). GPT-4o / Gemini / Pixtral recover `YOU'RE MELTING`.*  
3. *Beware the Woods (2022): dark poster; Google mangles `WOODS`→`WOODEN`. VLMs (and Rekognition) get it right — showing engine-to-engine variance inside “traditional OCR.”*
