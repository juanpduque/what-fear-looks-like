# The Anatomy of Fear — Essay Draft v1

> Numbers marked **[PILOT]** come from the 1,000-poster stratified sample (1950–2022).
> Replace with full-run figures after `--all --backfill --refresh` completes.
> Target length: ~2,000 words. Voice: Pudding-style — curious, precise, a little wicked.

---

## Hero

**THE ANATOMY OF FEAR**
We analyzed the colors of 32,540 horror movie posters spanning a century to answer one question: what does fear look like — and how has it changed?

## Intro

A horror poster has one job: scare you into a seat. But *how* it scares you is a fingerprint of its era. The painted monsters of the 1930s, the occult photography of the '70s, the black-and-red formula of the slasher boom, today's minimalist dread — each is a fossil of what its decade feared.

Fossils can be measured. For every poster in a 32,540-film database, we extracted its dominant palette, its brightness, its saturation, and how much of it is the color of blood.

We went in with three hypotheses. One survived, one died, and one turned into a better story than the one we were looking for.

## Part I — The Color River

Before the stories, the raw material: here is every hue in a century of horror, decade by decade.

Two currents are visible at a glance. The warm, painted palette of the studio era — those lurid pulp yellows and poster-paint oranges — thins out steadily after the 1960s. And the black rises like floodwater: from roughly a third of every poster in the 1950s **[PILOT: dark/grey pixels 29%]** to more than half today **[PILOT: 53% in the 2020s]**.

Horror posters didn't just change style. They changed physical substance — from images *of* things to images *hiding* things.

## Part II — Six Eras of Terror

**1920s–1930s: Painted Monsters.** Lithographed one-sheets sold the creature, not the fear. Universal's monsters loom in theatrical greens and sickly yellows — horror as carnival attraction. *[Backfill data pending — describe qualitatively until then, anchored on Nosferatu (1922), Dracula (1931), Frankenstein (1931).]*

**1940s–1950s: Atomic Pulp.** Radiation, invasion, paranoia — and the brightest posters horror would ever print. The 1950s are the high-water mark of light in our data: average brightness L\* 45.8 **[PILOT]**, barely a quarter of each poster in shadow. When the monster is a fifty-foot ant, you need daylight to show it off.

**1960s–1970s: The Occult Turn.** Photography replaces paint, and the devil moves into the suburbs. *Rosemary's Baby*, *The Exorcist*, *The Omen*: the poster stops showing you the monster because the monster might be your neighbor, your church, your child. The data catches the exact moment the lights start going out — dark pixels climb from 29% to 34% **[PILOT]**, and brightness begins a fall it will never recover from. This era also holds a quieter record: the least saturated posters of the century **[PILOT: 0.344]**. Not the digital 2000s — the analog '70s, all fog and newsprint flesh tones.

**1980s: Black & Red.** The slasher boom industrializes the formula: black void, a weapon, a scream, chrome type. Brightness collapses from 43 to 34 in a single decade **[PILOT]** — the steepest drop in our data. The VHS shelf gets blamed for a lot of this, deservedly: a poster now had to read as a two-inch thumbnail in a video store, and nothing reads faster than a knife on black.

**1990s–2000s: The Myth of the Cold Decade.** Ask anyone who lived through it: the '90s and 2000s were the era of desaturated horror — steel blues, surgical greens, that torture-porn grime. Our data says otherwise. Saturation *held steady* at 0.41 **[PILOT]** — higher than the '60s–'70s. What actually distinguishes the era is red. Blood-red pixel share peaks in the mid-'90s at 15.7% **[PILOT]** — not in the slasher '80s, where legend puts it. *Scream* didn't just revive the slasher; its marketing repainted it. The cold look we all remember was a color *temperature* shift, not a saturation drop — and the posters were redder than they'd ever been.

**2010s–today: Elevated Darkness.** Here is where we expected the story to turn around. A24 and the arthouse wave brought "daylight horror" — *Midsommar*'s flower-crowned sunshine, *Hereditary*'s lit dollhouses. We assumed the posters followed the films into the light.

They didn't. This is the darkest era ever measured: average brightness L\* 27.4, with over half of every poster near-black **[PILOT: 52%]**. *Midsommar* is the exception that proves the rule — a marketing decision so unusual it became the poster everyone remembers. The genre as a whole kept descending. Seventy years of data, and the light never came back.

## Part III — The Darkness Curve

*(Annotated chart. The single-sentence payoff, big type:)*

**Horror posters have gotten darker every decade for seventy years. We searched for the rebound. There isn't one.**

Why? Three suspects, none fully acquitted. Screens replaced print — a poster is now a thumbnail on Netflix, where black backgrounds make artwork pop and text legible. Grading got cheap — digital tools made crush-the-blacks the default aesthetic. And fear itself moved indoors — from creatures you could paint to atmospheres you can only suggest. The full 32k run will let us test the first suspect directly: if streaming drove it, the slope should steepen after 2007. **[FULL-RUN: check post-2007 slope]**

## Part IV — The Rise of Red

Red is horror's signature — the one color the genre owns outright. But its history is stranger than its reputation. It rises with the occult '70s, plateaus through the slasher '80s at around 12% **[PILOT]**, and hits its true peak twice: the meta-horror mid-'90s (15.7%) and a second spike around 2010 **[PILOT: 16.0%]** at the height of torture-porn marketing. The '80s slasher — the era everyone associates with blood-soaked posters — never actually led the league. Its posters were too busy being *black*.

## Explorer

*(Interactive: all posters, sorted by dominant color, year-range slider. Closing line above it:)*

Every nightmare we measured, in chronological order. Drag through the century and watch it go dark.

## Methodology (abridged)

Film list from TMDB (32,540 features tagged Horror; base dataset by Tanya Shapiro, TidyTuesday 2022, extended via TMDB API for pre-1950 and post-2022). Posters analyzed at 96×144 px. Palette: k-means (k=5) in CIELAB with saturation-weighted sampling, after "The Colour of Horror" (ACM EVMP 2022). Brightness = mean L\*. Red = hue 345°–15°, S>0.4, V>0.15. Pilot: stratified 1,000-poster sample; full run: every poster with valid artwork. Code and data on GitHub. This product uses the TMDB API but is not endorsed or certified by TMDB.

---

## Notas de producción (ES)

- Los tres "giros" del ensayo (no-rebote de luz, mito de los 90, pico rojo Scream) salen del piloto: **verificar que sobreviven al full run antes de publicar**.
- El hook de las 3 hipótesis (una sobrevive, una muere, una mejora) estructura todo el texto — mantenerlo aunque cambien los números.
- Falta decidir: cameo de pósters reales por era (30-40 seleccionados a mano) — hacerlo tras el full run con los extremos de cada década (`posters.csv`).
- Longitud actual ≈ 1,100 palabras; crecerá con la era 1920-40 tras el backfill y 2-3 datos de contexto de industria (Stephen Follows) por capítulo.
