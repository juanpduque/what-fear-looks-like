#!/usr/bin/env python3
"""Build community horror-poster manifest (essay corpus ∪ all-lang gap).

Does not overwrite essay CSVs. Writes:
  data/community/community_manifest.csv
  data/community/README.md

DetectText columns come from:
  poster_ocr_rek_text.csv (essay) ∪ poster_ocr_rek_text_alllang.csv

  python3 build_community_manifest.py
"""
from __future__ import annotations

import csv
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
OUT_DIR = DATA / "community"
MANIFEST = OUT_DIR / "community_manifest.csv"
README = OUT_DIR / "README.md"

FIELDS = [
    "id",
    "title",
    "original_title",
    "original_language",
    "release_date",
    "year",
    "runtime",
    "poster_path",
    "in_essay_corpus",
    "has_local_poster",
    "detecttext_full_ocr",
    "detecttext_n_lines",
    "detecttext_empty",
    "detecttext_error",
    "detecttext_source",  # essay | allang
]


def load_rek(path: Path, source: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except Exception:
                continue
            out[pid] = {**r, "_source": source}
    return out


def load_horror() -> dict[int, dict]:
    out: dict[int, dict] = {}
    with (DATA / "horror_movies.csv").open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(float(r["id"]))
            except Exception:
                continue
            out[pid] = r
    return out


def load_essay_ids() -> set[int]:
    ids: set[int] = set()
    with (DATA / "posters.csv").open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                ids.add(int(r["id"]))
            except Exception:
                pass
    return ids


def load_paths() -> dict[int, str]:
    paths: dict[int, str] = {}
    for src in (DATA / "horror_movies.csv", DATA / "poster_paths_backfill.csv"):
        if not src.exists():
            continue
        with src.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(float(r["id"]))
                except Exception:
                    continue
                p = (r.get("poster_path") or "").strip()
                if p.startswith("/") and pid not in paths:
                    paths[pid] = p
    return paths


def year_of(date: str) -> str:
    d = (date or "").strip()
    return d[:4] if len(d) >= 4 and d[:4].isdigit() else ""


def main() -> int:
    essay = load_essay_ids()
    horror = load_horror()
    paths = load_paths()
    rek_essay = load_rek(DATA / "poster_ocr_rek_text.csv", "essay")
    rek_allang = load_rek(DATA / "poster_ocr_rek_text_alllang.csv", "allang")
    # essay wins on overlap
    rek = {**rek_allang, **rek_essay}

    posters = DATA / "posters"
    ids = sorted(set(rek) | essay)
    # community set = everyone with DetectText OR essay membership with local poster
    # Prefer: DetectText union (the gift OCR layer)
    ids = sorted(rek.keys())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_empty = n_essay = 0
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for pid in ids:
            meta = horror.get(pid, {})
            r = rek.get(pid, {})
            text = (r.get("full_ocr") or "").strip()
            empty = not text
            if empty:
                n_empty += 1
            in_essay = pid in essay
            if in_essay:
                n_essay += 1
            local = (posters / f"{pid}.jpg").exists() or (posters / f"{pid}.png").exists()
            rd = meta.get("release_date") or ""
            w.writerow(
                {
                    "id": pid,
                    "title": meta.get("title") or "",
                    "original_title": meta.get("original_title") or "",
                    "original_language": meta.get("original_language") or "",
                    "release_date": rd,
                    "year": year_of(rd),
                    "runtime": meta.get("runtime") or "",
                    "poster_path": paths.get(pid, "") or (meta.get("poster_path") or ""),
                    "in_essay_corpus": "1" if in_essay else "0",
                    "has_local_poster": "1" if local else "0",
                    "detecttext_full_ocr": r.get("full_ocr") or "",
                    "detecttext_n_lines": r.get("n_lines") or "",
                    "detecttext_empty": "1" if empty else "0",
                    "detecttext_error": r.get("error") or "",
                    "detecttext_source": r.get("_source") or "",
                }
            )

    readme = f"""# Community horror poster OCR set

Two products live in this project:

1. **Essay corpus** (`data/posters.csv`, ~{n_essay:,} rows here flagged `in_essay_corpus=1`): filtered EN horror used for *What Fear Looks Like*.
2. **Community set** (this manifest): TMDB horror posters with **Amazon Rekognition DetectText**, including titles outside the essay filters (other languages, shorts, etc.).

## File

- `{MANIFEST.name}` — **{len(ids):,}** ids
- DetectText non-empty: **{len(ids) - n_empty:,}**
- DetectText empty: **{n_empty:,}**
- Overlap with essay corpus: **{n_essay:,}**

## Sources

- Essay DetectText: `../poster_ocr_rek_text.csv`
- All-lang gap DetectText: `../poster_ocr_rek_text_alllang.csv`
- Metadata: `../horror_movies.csv`

## License / attribution

Posters remain © their rights holders; metadata via TMDB. OCR text is model output (Rekognition DetectText). Cite TMDB and this project if you redistribute derivatives.

## Optional enrichments

Textract / Comprehend for the all-lang gap land in `*_alllang.csv` beside the essay files when available.
"""
    README.write_text(readme, encoding="utf-8")
    print(f"wrote {MANIFEST} n={len(ids):,} essay={n_essay:,} empty_ocr={n_empty:,}")
    print(f"wrote {README}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
