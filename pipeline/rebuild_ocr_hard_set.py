#!/usr/bin/env python3
"""Regenerate OCR hard sample after QA title fixes / exclusions.

Policy (2026-07-31):
  - Start from original hard definition: ocr_pilot_v2 qwen rows with
    stored title_overlap_score < 1 (the historical hard12).
  - Apply data/qa/ocr_qa_title_overrides.csv → rescore OCR text vs new title.
  - Drop ids in data/qa/ocr_qa_exclude_ids.csv.
  - Drop ids whose rescored overlap is now >= 1 (false hard from bad metadata).
  - Sync sample_ids.txt / sample_meta.csv across hard QA dirs.
  - Patch SoT titles in posters.csv + horror_movies.csv for overrides.
  - Write hard ladder snapshot + NOTES.

Usage:
  python3 rebuild_ocr_hard_set.py
  python3 rebuild_ocr_hard_set.py --also-article
"""
from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from pathlib import Path

from ocr_metrics import title_overlap_score

PIPE = Path(__file__).resolve().parent
DATA = PIPE / "data"
QA = DATA / "qa"
V2_RESULTS = QA / "ocr_pilot_v2" / "results.csv"
OVERRIDES_CSV = QA / "ocr_qa_title_overrides.csv"
EXCLUDE_CSV = QA / "ocr_qa_exclude_ids.csv"
HARD_PRIMARY = QA / "ocr_qwen_hard"

# Dirs that share the hard sample id list
HARD_MIRROR_DIRS = [
    QA / "ocr_qwen_hard",
    QA / "ocr_kimi_hard",
    QA / "ocr_ppocrv6_hard",
    QA / "ocr_qwen_hard_crop",
    QA / "ocr_hard12_new",
    QA / "ocr_hard12_openrouter",
]


def load_overrides() -> dict[int, str]:
    out: dict[int, str] = {}
    if not OVERRIDES_CSV.exists():
        return out
    for r in csv.DictReader(OVERRIDES_CSV.open(encoding="utf-8")):
        out[int(r["id"])] = str(r["title"]).strip()
    return out


def load_excludes() -> dict[int, str]:
    out: dict[int, str] = {}
    if not EXCLUDE_CSV.exists():
        return out
    for r in csv.DictReader(EXCLUDE_CSV.open(encoding="utf-8")):
        out[int(r["id"])] = str(r.get("reason") or "").strip()
    return out


def patch_sot_titles(overrides: dict[int, str]) -> None:
    for path in (DATA / "posters.csv", DATA / "horror_movies.csv"):
        if not path.exists():
            continue
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        fields = list(rows[0].keys()) if rows else []
        n = 0
        for r in rows:
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if pid in overrides and r.get("title") != overrides[pid]:
                r["title"] = overrides[pid]
                # keep original_title in sync when present and was the old aka
                if "original_title" in r and pid == 77399:
                    r["original_title"] = overrides[pid]
                if "original_title" in r and pid == 940187:
                    r["original_title"] = overrides[pid]
                n += 1
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"patched {n} titles in {path}", flush=True)


def historical_hard_qwen_rows() -> list[dict]:
    """Original hard12: stored qwen score < 1 in pilot_v2."""
    rows = []
    for r in csv.DictReader(V2_RESULTS.open(encoding="utf-8")):
        if r.get("model") != "qwen":
            continue
        try:
            s = float(r.get("title_overlap_score") or "")
        except ValueError:
            continue
        if s < 1:
            rows.append(r)
    rows.sort(key=lambda r: int(r["id"]))
    return rows


def rebuild_hard(
    overrides: dict[int, str], excludes: dict[int, str]
) -> tuple[list[dict], list[dict]]:
    """Return (kept_meta_rows, dropped_rows_with_reason)."""
    posters = {
        int(r["id"]): r
        for r in csv.DictReader((DATA / "posters.csv").open(encoding="utf-8"))
    }
    kept: list[dict] = []
    dropped: list[dict] = []
    for r in historical_hard_qwen_rows():
        pid = int(r["id"])
        old_title = str(r.get("title") or "")
        new_title = overrides.get(pid, old_title)
        text = str(r.get("text") or "")
        old_score = float(r["title_overlap_score"])
        new_score = title_overlap_score(text, new_title)
        year = posters.get(pid, {}).get("year") or r.get("year") or ""
        base = {
            "id": pid,
            "title": new_title,
            "year": year,
            "prior_qwen_overlap_stored": old_score,
            "prior_qwen_overlap": round(new_score, 4),
            "old_title": old_title,
        }
        if pid in excludes:
            dropped.append({**base, "drop_reason": f"exclude: {excludes[pid]}"})
            continue
        if new_score >= 1.0 - 1e-9:
            dropped.append(
                {
                    **base,
                    "drop_reason": "rescored_perfect_after_title_fix",
                }
            )
            continue
        kept.append(base)
    return kept, dropped


def write_hard_files(kept: list[dict], dropped: list[dict]) -> None:
    HARD_PRIMARY.mkdir(parents=True, exist_ok=True)
    ids = [int(r["id"]) for r in kept]
    ids_txt = "\n".join(str(i) for i in ids) + ("\n" if ids else "")
    meta_fields = [
        "id",
        "title",
        "year",
        "prior_qwen_overlap",
        "prior_qwen_overlap_stored",
        "old_title",
    ]

    for d in HARD_MIRROR_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        (d / "sample_ids.txt").write_text(ids_txt, encoding="utf-8")
        with (d / "sample_meta.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=meta_fields, extrasaction="ignore")
            w.writeheader()
            for r in kept:
                w.writerow(r)
        print(f"wrote {d / 'sample_ids.txt'} n={len(ids)}", flush=True)

    drop_path = HARD_PRIMARY / "hard_qc_dropped.csv"
    with drop_path.open("w", encoding="utf-8", newline="") as f:
        fields = [
            "id",
            "title",
            "year",
            "old_title",
            "prior_qwen_overlap_stored",
            "prior_qwen_overlap",
            "drop_reason",
        ]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in dropped:
            w.writerow(r)
    print(f"wrote {drop_path} n={len(dropped)}", flush=True)

    notes = HARD_PRIMARY / "NOTES.md"
    notes.write_text(
        f"""# OCR Qwen hard mini-pilot notes

- **Hard set (regenerated 2026-07-31):** **{len(ids)}** ids
- Base definition: ocr_pilot_v2 `model=qwen` with **stored** `title_overlap_score < 1` (historical hard12)
- QC:
  - Title overrides: `{OVERRIDES_CSV.relative_to(PIPE)}`
  - Exclusions: `{EXCLUDE_CSV.relative_to(PIPE)}`
  - Dropped if rescored overlap ≥ 1 after title fix (metadata false hard)
- Dropped rows: `hard_qc_dropped.csv`
- Poster sources: 6 true homolog / rest w342 (see `poster_sources.csv` where present)
- Models: qwen2b-hard = Qwen2-VL-2B-Instruct; qwen7b-hard = Qwen2-VL-7B-Instruct @ 4bit

## Kept ids

{chr(10).join(f"- `{r['id']}` — {r['title']} (qwen rescored={r['prior_qwen_overlap']})" for r in kept)}

## Dropped

{chr(10).join(f"- `{r['id']}` — {r.get('old_title') or r['title']}: {r['drop_reason']}" for r in dropped)}
""",
        encoding="utf-8",
    )
    print(f"wrote {notes}", flush=True)


def collect_hard_ladder(ids: list[int], overrides: dict[int, str]) -> Path:
    """Rescore known result CSVs on hard ids → ocr_article/ladder_hard_qc.csv."""
    id_set = set(ids)
    sources = [
        QA / "ocr_pilot_v2" / "results.csv",
        QA / "ocr_qwen_hard" / "results.csv",
        QA / "ocr_kimi_hard" / "results.csv",
        QA / "ocr_ppocrv6_hard" / "results.csv",
        QA / "ocr_qwen_hard_crop" / "results.csv",
        QA / "ocr_hard12_openrouter" / "results.csv",
        QA / "ocr_pilot_v2_gemma31" / "results.csv",
    ]
    # model → id → score
    scores: dict[str, dict[int, float]] = {}
    for path in sources:
        if not path.exists():
            continue
        for r in csv.DictReader(path.open(encoding="utf-8")):
            try:
                pid = int(r["id"])
            except (TypeError, ValueError):
                continue
            if pid not in id_set:
                continue
            if str(r.get("status") or "ok") not in ("ok", ""):
                continue
            model = str(r["model"])
            title = overrides.get(pid, str(r.get("title") or ""))
            text = str(r.get("text") or "").replace("\\n", "\n")
            # Prefer rescoring from text when present
            if text.strip():
                s = title_overlap_score(text, title)
            else:
                try:
                    s = float(r.get("title_overlap_score") or 0)
                except ValueError:
                    s = 0.0
            # Prefer stored score for continuity unless title was overridden
            if int(r["id"]) not in overrides:
                try:
                    s = float(r.get("title_overlap_score") or s)
                except ValueError:
                    pass
            scores.setdefault(model, {})[pid] = s

    out_dir = QA / "ocr_article"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "ladder_hard_qc.csv"
    rows = []
    for model, by_id in scores.items():
        if len(by_id) < len(ids) - 1:
            continue
        vals = [by_id.get(i, 0.0) for i in ids if i in by_id]
        if len(vals) < len(ids) - 1:
            continue
        # require full coverage ideally
        if len(by_id) < len(ids):
            continue
        vals = [by_id[i] for i in ids]
        rows.append(
            {
                "model": model,
                "n": len(vals),
                "mean_overlap": round(sum(vals) / len(vals), 4),
                "median_overlap": round(sorted(vals)[len(vals) // 2], 4),
                "n_perfect": sum(1 for v in vals if v >= 1.0 - 1e-9),
            }
        )
    rows.sort(key=lambda r: -r["mean_overlap"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    fields = ["rank", "model", "n", "mean_overlap", "median_overlap", "n_perfect"]
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out} ({len(rows)} models)", flush=True)
    for r in rows[:15]:
        print(
            f"  #{r['rank']:02d} {r['model']:<28} mean={r['mean_overlap']:.4f} "
            f"perfect={r['n_perfect']}/{r['n']}",
            flush=True,
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--also-article",
        action="store_true",
        help="run build_ocr_article_benchmark.py after rebuild",
    )
    ap.add_argument(
        "--no-patch-sot",
        action="store_true",
        help="do not rewrite posters.csv / horror_movies.csv titles",
    )
    args = ap.parse_args()

    overrides = load_overrides()
    excludes = load_excludes()
    print(f"overrides={overrides}", flush=True)
    print(f"excludes={excludes}", flush=True)

    if not args.no_patch_sot:
        patch_sot_titles(overrides)

    kept, dropped = rebuild_hard(overrides, excludes)
    write_hard_files(kept, dropped)
    ids = [int(r["id"]) for r in kept]
    collect_hard_ladder(ids, overrides)

    print(f"\nHARD n={len(ids)} → {ids}", flush=True)
    print(f"DROPPED n={len(dropped)}", flush=True)

    if args.also_article:
        cmd = [sys.executable, str(PIPE / "build_ocr_article_benchmark.py")]
        print("running:", " ".join(cmd), flush=True)
        subprocess.check_call(cmd, cwd=str(PIPE))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
