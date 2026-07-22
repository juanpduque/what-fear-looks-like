# The Anatomy of Fear — Essay Draft

> v3 — figures recalculated on the **filtered** corpus (n = **18,716** posters, 1920–2022).
> Exclusions: TMDB `Animation` + `Music` + `original_language` ≠ `en` (lists in `pipeline/data/excluded_*.csv`).
> **Kept:** TMDB `TV Movie` telefilms (~530 in the filtered corpus) — not series; still one-sheet marketing.
> Chart series: `site/data/series.js` via `pipeline/export_site_series.py`.
> Target length: ~2,000 words. Voice: Pudding-style — curious, precise, a little wicked.

---

## Hero

**THE ANATOMY OF FEAR**
We analyzed the colors of **18,716** horror movie posters spanning a full century (1920–2022) to answer one question: what does fear look like — and how has it changed?

## Intro

A horror poster has one job: scare you into a seat. But *how* it scares you is a fingerprint of its era. The painted monsters of the 1930s, the occult photography of the '70s, the black-and-red formula of the slasher boom, today's minimalist dread — each is a fossil of what its decade feared.

Fossils can be measured. From a database of ~32,500 films tagged Horror on TMDB we analyzed every poster with usable artwork that survived our filters — **18,716** of them — extracting each one's dominant palette, brightness, saturation, and how much of it is the color of blood. We dropped Animation and Music titles, and non-English originals (poster lettering skewed typography/OCR).

We went in with three hypotheses. One survived, one died, and one turned into a better story than the one we were looking for.

## Part I — The Color River

Before the stories, the raw material: here is every hue in a century of horror, decade by decade.

Two currents are visible at a glance. The warm, painted palette of the studio era — those lurid pulp yellows and poster-paint oranges — shrinks from **27%** of every poster in the 1950s to **13%** today. And black/grey rises like floodwater: **45%** of every poster in the 1950s, **61%** in the 2020s. (One eddy worth a caption: blue flares to its peak in the 1980s — the neon glow of the VHS slasher, **13%** of pixels.)

Horror posters didn't just change style. They changed physical substance — from images *of* things to images *hiding* things.

## Part II — Six Eras of Terror

**1920s–1930s: Painted Monsters.** Lithographed one-sheets sold the creature, not the fear — but the backfill data held a surprise: these posters were *darker* than the atomic age that followed (L\* **43.7** for 1920–49, below the mid-century peak). The century's brightness is not a slide but a mountain, and expressionism is its first slope — Nosferatu's shadow was printed, not just projected. Red barely existed: **6.6%** of pixels, half its later norm. Horror before blood.

**1940s–1950s: Atomic Pulp.** Radiation, invasion, paranoia — and the climb toward the brightest posters horror would ever print. By the **1950s** average brightness is already L\* **48.6**, with barely a quarter of each poster (**26%**) in shadow; the absolute decade peak lands in the **1960s** (L\* **49.1**). When the monster is a fifty-foot ant, you need daylight to show it off.

**1960s–1970s: The Occult Turn.** Photography replaces paint, and the devil moves into the suburbs. *Rosemary's Baby*, *The Exorcist*, *The Omen*: the poster stops showing you the monster because the monster might be your neighbor, your church, your child. The data catches the exact moment the lights start going out — dark pixels climb from the mid-20s into the high 30s, and brightness begins a fall it will never recover from. This era also holds a quieter record: the least saturated posters of the century (**0.35** in the 1960s). Not the digital 2000s — the analog '60s and '70s, all fog and newsprint flesh tones.

**1980s: Black & Red.** The slasher boom industrializes the formula: black void, a weapon, a scream, chrome type. Brightness collapses from **41.1** (1970s) to **34.1** in a single decade — the steepest drop in our data. The VHS shelf gets blamed for a lot of this, deservedly: a poster now had to read as a two-inch thumbnail in a video store, and nothing reads faster than a knife on black. One thing the '80s did add: blue. Neon, chrome, and moonlight push blue to its all-time peak (**13%** of pixels).

**1990s–2000s: The Myth of the Cold Decade.** Ask anyone who lived through it: the '90s and 2000s were the era of desaturated horror — steel blues, surgical greens, that torture-porn grime. Our data says otherwise. Saturation *held steady* around **0.42** — higher than the '60s–'70s (~0.36). What actually distinguishes the era is red — and the close-up. Blood-red pixel share hits its all-time rolling peak around **2001** (~**14%**) — not in the slasher '80s, where legend puts it. And face detection reveals the era's real signature: not *more* faces, but *bigger* ones. Average face size on the sheet peaks in **1998** at ~**10%** of the sheet — nearly double its historic level. Look at the *Scream* one-sheet: six faces, one of them filling the entire background. This is the celebrity close-up era — Neve Campbell, Jennifer Love Hewitt, bankable young faces sold at maximum zoom. Late-'90s / early-2000s horror sold two things above all: blood, and celebrity.

**2010s–today: Elevated Darkness.** Here is where we expected the story to turn around. A24 and the arthouse wave brought "daylight horror" — *Midsommar*'s flower-crowned sunshine, *Hereditary*'s lit dollhouses. We assumed the posters followed the films into the light.

They didn't. This is the darkest era ever measured: average brightness L\* **30.0** across **11,215** posters (2010–2022), with about half of every poster (**49%**) near-black. And the faces are leaving: in the 1940s, showing a face was nearly mandatory — **83%** of posters had one, the century's peak; today fewer than half do (**47%**), the low point of a long retreat. The face sold the matinee ticket, the VHS box, the multiplex; the streaming thumbnail sells an *object* — a house, a hand, a shape in the dark. *Midsommar* is the exception that proves the rule — a marketing decision so unusual it became the poster everyone remembers. The genre as a whole kept descending. From the atomic daylight peak around **1960**, sixty years of data, and the light never came back.

## Part III — The Darkness Curve

*(Annotated chart. The single-sentence payoff, big type:)*

**Horror posters have gotten darker every decade since the atomic daylight peak around 1960. We searched for the rebound. There isn't one.**

Why? Three suspects. The obvious one — streaming — we can actually put on trial: if Netflix thumbnails drove the darkening, the slope should steepen after 2007. It doesn't. Posters darkened at roughly the same rate before streaming existed and after. Acquitted. Which leaves the deeper suspects: grading got cheap — digital tools made crush-the-blacks the default aesthetic — and fear itself moved indoors, from creatures you could paint to atmospheres you can only suggest. Whatever is driving it has been pushing, at the same steady rate, since the Cold War was still young.

## Part IV — The Rise of Red

Red is horror's signature — the one color the genre owns outright. But its history is stranger than its reputation. It rises with the occult '70s, *dips* or plateaus through parts of the slasher '80s, and hits its all-time peak at the **meta-horror turn of the millennium** — not in the slasher '80s, where legend puts it. The '80s slasher — the era everyone associates with blood-soaked posters — never actually led the league. Its posters were too busy being *black*. And since 2010, red has quietly retreated toward mid-century levels: elevated horror doesn't bleed on the one-sheet.

## Part VII — The Monster Census

We asked a vision model one question about every poster: *what creature is on it?* The answer is a dynastic succession of fear.

In the 1950s, the throne belongs to the atomic age — giant monsters (**5.9%** of all posters) and aliens (**5.3%**, a share they would never approach again). The 1970s crown the witch: **6.8%** at the occult peak, precisely when *Rosemary's Baby* and *The Exorcist* moved the devil into the suburbs. The 1980s belong to the masked killer (**8.2%**, the slasher boom, measured). The 2000s stage the zombie explosion — from ~2% to **6.9%** in a single decade, the *28 Days Later* and *Walking Dead* contagion years, fear as pandemic.

And then there is the ghost — and the century's most elegant twist. The spiritualist 1920s put spectres on **12%** of posters, the highest share in our data; the mid-century buried them under monsters with bodies; and then, decade by decade, the ghost climbed back — **5.7%** in the '90s, **9.1%** today. A hundred years of creatures, and the census closes where it opened: the century of fear begins and ends with a ghost. The monster of the streaming age is the one you can't fight, can't shoot, and can't see. Horror iconography rematerialized once — into kaiju, killers, and contagion — and has spent the rest of the century dissolving back into absence. It is the same story the Darkness Curve tells, written in monsters instead of pixels.

## Explorer

*(Interactive: all posters, sorted by dominant color, year-range slider. Closing line above it:)*

Every nightmare we measured, in chronological order. Drag through the century and watch it go dark.

## Methodology (abridged)

Film list from TMDB (base dataset by Tanya Shapiro, TidyTuesday 2022, covering 1950–2022; extended to 1920–1949 via the TMDB discover API). We analyzed **18,716** posters with usable artwork, 1920–2022, after excluding titles genre-tagged Animation or Music and films whose TMDB `original_language` is not English (~8,907) — non-English lettering skewed typography/OCR. TMDB `TV Movie` telefilms are kept (single films for television, not series). Exclusion lists live in `pipeline/data/excluded_*.csv` and are applied with `python3 apply_exclusions.py`, which also regenerates decade aggregates and `site/data/series.js`. Pre-1950 decades carry smaller samples; their decade-level figures are noisier. Posters analyzed at 96×144 px. Palette: k-means (k=5) in CIELAB with saturation-weighted sampling, after "The Colour of Horror" (ACM EVMP 2022). Brightness = mean L\*. Red = hue 345°–15°, S>0.4, V>0.15. Hue families computed on chromatic pixels (S>0.15, V>0.12). Face detection: YuNet (OpenCV FaceDetectorYN) at 320 px width, confidence 0.6, validated against hand-checked artwork (e.g., the six faces of the *Scream* one-sheet). We initially ran Haar cascades and discarded the results: Haar sees only photographic frontal faces and invented a spurious '90s peak in counts. YuNet detects painted faces reliably — the **1940s** show the *highest* face share of the century (**83%**) — but small tilted or profile faces can still escape it, so counts are floors. Creature census: CLIP (ViT-B/32) zero-shot against an 18-label taxonomy with prompt ensembles, validated 10/10 on hand-checked artwork; labels below 0.5 confidence are excluded, so shares are conservative floors and decade-to-decade comparisons are the deliverable. External validity check: the witch peaks exactly in the occult '70s, the masked killer in the slasher '80s, the zombie in the 2000s — the model recovers film history it was never told. Semantic "blood" (CLIP zero-shot on poster patches) is a stratified sample (n = **1,721** after exclusions), not a full run. Robustness: the dataset spans everything TMDB tags as horror that survives the filters, from *It* to zero-budget indies. The Darkness Curve survives restriction to mainstream films (titles with 100+ votes) — with one refinement: mainstream horror hit bottom brightness earlier, while the long tail of independent horror darkened more gradually. Code and data on GitHub. This product uses the TMDB API but is not endorsed or certified by TMDB.

---

## Notas de producción (ES)

- Los tres "giros" del ensayo (no-rebote de luz, mito de los 90, pico rojo meta-horror) **sobreviven al corpus filtrado** (n = 18,716); cifras v3 arriba.
- Pico de brillo: década **1960s** (L\* 49.1), no solo 1950s — alinear copy del sitio y del draft.
- Pico rojo: rolling ~**2001**, no solo “Scream 1997”; narrar como *turn of the millennium*.
- Caras 1940s: **83%** (no 85%). Face-area peak: **1998**.
- El hook de las 3 hipótesis estructura todo el texto — mantenerlo aunque cambien los números.
- **TV Movies: se quedan.** Son telefilms (película unitaria para TV), no series. ~530 en el corpus filtrado. No crear `excluded_tv_movie.csv` salvo que el framing pase a “solo cine teatral”.
- Cameos de pósters por era: ya hay strips en `site/index.html`; revisar si algún specimen cayó por exclusiones.
- Longitud ≈ 1,100 palabras; crecer con 2–3 datos de industria (Stephen Follows) por capítulo si hace falta.
- Tras cualquier cambio de `excluded_*.csv`: `python3 apply_exclusions.py` (regenera agregados + `series.js`).
