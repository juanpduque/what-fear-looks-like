#!/usr/bin/env python3
"""Build the canonical published corpus (data/canonical_ids.txt).

Criteria, applied in order (first failing filter is the drop reason):
  1. tmdb_ok        TMDB /movie/{id} responds (fetch_tmdb_details.py cache)
  2. horror         current TMDB genres include "Horror"
  3. english        original_language == "en"
  4. released       status == "Released" and release_date <= today
  5. not_adult      adult is False
  6. genre_ok       genres exclude Animation, Music, TV Movie
  7. not_excluded   id not in any data/excluded_*.csv (except *_review.csv)
  8. valid_year     1900 <= posters.csv year <= current year
  9. has_poster     not in qa/no_poster and art is servable (TMDB path or
                    local site/assets/posters/{id}.jpg)

Base = ids with poster metrics (posters.csv).

Outputs:
  data/canonical_ids.txt
  data/qa/corpus/corpus_dropped.csv  (id, reason)
  data/qa/corpus/corpus_funnel.json
  docs/CORPUS.md

  python3 build_corpus.py
  python3 build_corpus.py --today 2026-10-06
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / "data"
DETAILS = DATA / "qa" / "tmdb_details" / "tmdb_details.jsonl"
NO_POSTER = DATA / "qa" / "no_poster" / "no_poster_ids.txt"
ASSETS = ROOT / "site" / "assets" / "posters"
OUT_IDS = DATA / "canonical_ids.txt"
QA = DATA / "qa" / "corpus"
DOC = ROOT / "docs" / "CORPUS.md"

BAD_GENRES = ("Animation", "Music", "TV Movie")
MIN_YEAR = 1900

FILTERS = [
    ("tmdb_ok", "Ficha TMDB vigente"),
    ("horror", "Género TMDB incluye Horror"),
    ("english", "Idioma original inglés"),
    ("released", "Estrenada (status Released y fecha ≤ hoy)"),
    ("not_adult", "Sin filtro de adulto"),
    ("genre_ok", "Sin Animation / Music / TV Movie"),
    ("not_excluded", "Fuera de listas excluded_*.csv"),
    ("valid_year", "Año válido"),
    ("has_poster", "Con póster servible"),
]


def read_ids(path: Path) -> set[int]:
    if not path.is_file():
        return set()
    return {int(x) for x in path.read_text().split() if x.strip().isdigit()}


def load_details() -> dict[int, dict]:
    if not DETAILS.is_file():
        raise SystemExit(f"falta {DETAILS} — corre fetch_tmdb_details.py")
    out: dict[int, dict] = {}
    for line in DETAILS.open(encoding="utf-8"):
        line = line.strip()
        if line:
            rec = json.loads(line)
            out[int(rec["id"])] = rec
    return out


def load_excluded() -> dict[int, str]:
    out: dict[int, str] = {}
    for path in sorted(DATA.glob("excluded_*.csv")):
        if path.name.endswith("_review.csv"):
            continue
        tag = path.stem.removeprefix("excluded_")
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    out.setdefault(int(r["id"]), tag)
                except (KeyError, ValueError):
                    pass
    return out


def load_local_paths() -> set[int]:
    have: set[int] = set()
    for src in (DATA / "horror_movies.csv", DATA / "poster_paths_backfill.csv"):
        if not src.exists():
            continue
        with src.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                p = r.get("poster_path") or ""
                if p.startswith("/"):
                    try:
                        have.add(int(r["id"]))
                    except (KeyError, ValueError):
                        pass
    if ASSETS.is_dir():
        have |= {int(p.stem) for p in ASSETS.glob("*.jpg") if p.stem.isdigit()}
    return have


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args()
    today = args.today
    max_year = int(today[:4])

    years: dict[int, int] = {}
    with (DATA / "posters.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                years.setdefault(int(r["id"]), int(float(r["year"])))
            except (KeyError, ValueError):
                pass

    details = load_details()
    excluded = load_excluded()
    no_poster = read_ids(NO_POSTER)
    servable = load_local_paths()

    def reason(pid: int) -> str | None:
        d = details.get(pid)
        if not d or d.get("http") != 200:
            return "tmdb_ok"
        genres = d.get("genres") or []
        if "Horror" not in genres:
            return "horror"
        if d.get("original_language") != "en":
            return "english"
        rd = d.get("release_date") or ""
        if d.get("status") != "Released" or not rd or rd > today:
            return "released"
        if d.get("adult"):
            return "not_adult"
        if any(g in genres for g in BAD_GENRES):
            return "genre_ok"
        if pid in excluded:
            return "not_excluded"
        if not (MIN_YEAR <= years[pid] <= max_year):
            return "valid_year"
        if pid in no_poster or pid not in servable:
            return "has_poster"
        return None

    dropped: list[tuple[int, str, str]] = []
    keep: list[int] = []
    for pid in sorted(years):
        why = reason(pid)
        if why is None:
            keep.append(pid)
        else:
            detail = excluded.get(pid, "") if why == "not_excluded" else ""
            dropped.append((pid, why, detail))

    funnel = [{"step": "base", "label": "Pósters con métricas", "n": len(years)}]
    left = len(years)
    for key, label in FILTERS:
        lost = sum(1 for _, w, _ in dropped if w == key)
        left -= lost
        funnel.append({"step": key, "label": label, "dropped": lost, "n": left})
    assert left == len(keep)

    by_list: dict[str, int] = {}
    for _, w, det in dropped:
        if w == "not_excluded":
            by_list[det] = by_list.get(det, 0) + 1

    OUT_IDS.write_text("\n".join(str(i) for i in keep) + "\n")
    QA.mkdir(parents=True, exist_ok=True)
    with (QA / "corpus_dropped.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "reason", "detail"])
        w.writerows(dropped)
    summary = {
        "today": today,
        "n": len(keep),
        "funnel": funnel,
        "excluded_lists": dict(sorted(by_list.items(), key=lambda x: -x[1])),
        "year_range": [min(years[i] for i in keep), max(years[i] for i in keep)],
    }
    (QA / "corpus_funnel.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    write_doc(summary)

    for row in funnel:
        extra = f"  (-{row['dropped']:,})" if "dropped" in row else ""
        print(f"  {row['label']:45s} {row['n']:7,}{extra}")
    print(f"canonical n={len(keep):,} -> {OUT_IDS.relative_to(ROOT)}")


def write_doc(s: dict) -> None:
    lines = [
        "# Corpus canónico",
        "",
        "Criterio: **películas de terror en inglés, ya estrenadas, con póster, sin "
        "exclusiones, con año válido y sin filtro de adulto; se quitan animación, "
        "musicales y TV Movie.**",
        "",
        "Fuente de verdad: `pipeline/data/canonical_ids.txt`, generado por "
        "`pipeline/build_corpus.py` a partir de metadatos TMDB vigentes "
        "(`pipeline/fetch_tmdb_details.py`). Todos los builders del sitio "
        "(`build_site.py`) filtran por este listado; los CSV crudos no se mutan.",
        "",
        f"Fecha de corte: `{s['today']}` · **n = {s['n']:,}** · años "
        f"{s['year_range'][0]}–{s['year_range'][1]}",
        "",
        "## Embudo",
        "",
        "| Paso | Quita | Quedan |",
        "|---|---:|---:|",
    ]
    for row in s["funnel"]:
        lost = f"{row['dropped']:,}" if "dropped" in row else ""
        lines.append(f"| {row['label']} | {lost} | {row['n']:,} |")
    lines += [
        "",
        "Cada película cuenta solo en el primer filtro que no cumple "
        "(`pipeline/data/qa/corpus/corpus_dropped.csv`).",
        "",
        "## Listas de exclusión que aún quitaron películas",
        "",
    ]
    if s["excluded_lists"]:
        for k, v in s["excluded_lists"].items():
            lines.append(f"- `excluded_{k}.csv`: {v:,}")
    else:
        lines.append("- ninguna")
    lines += [
        "",
        "## Reglas",
        "",
        "- **Terror**: género TMDB actual incluye `Horror` (no basta etiqueta de comunidad).",
        "- **Estrenada**: `status == Released` y `release_date` ≤ fecha de corte.",
        "- **Año válido**: año del análisis entre 1900 y el año de corte (sin 9999).",
        "- **Póster**: arte servible (path TMDB o asset local OMDb/actual) y fuera de `no_poster`.",
        "- Regenerar: `python3 pipeline/fetch_tmdb_details.py && python3 pipeline/build_corpus.py "
        "&& python3 pipeline/build_site.py`.",
        "",
    ]
    DOC.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
