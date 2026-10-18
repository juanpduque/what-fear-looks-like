#!/usr/bin/env python3
"""Build a single wide master table joining every metric CSV by id.

Phase 1: identity spine — union of ids across all raw candidate sources
(horror + community + genre expansions), with core metadata (title, year,
original_language, poster_path, which source(s) each id came from).

Phase 2a (this run): color + CLIP/SigLIP semantic metrics. Each CLIP metric
was run separately per genre corpus (horror/scifi/mystery/thriller), so the
same poster can have up to 4 slightly different results — verified this is
run-to-run numeric jitter (median diff ~0.001), not a real disagreement,
EXCEPT for categorical labels (census/medium) which genuinely disagree on
~4% of overlapping ids. Resolution:
  - continuous columns (attributes, fear_axis axis, typography axis, color):
    average across variants
  - categorical + score columns (census label/score, medium painted/p_painted):
    highest score wins, flag disagreement in a *_conflict column so it stays
    auditable instead of silently dropped
  - SigLIP metrics already cover the full corpus in one file each (no genre
    variants to merge)

Phase 3+ (later): OCR/language QA, perceptual scores (pyiqa/NIMA/etc),
enrichment (Rekognition/Nova/Comprehend).

  python3 build_master_dataset.py            # phase 1 (spine) + phase 2a
  python3 build_master_dataset.py --spine-only

Output: data/master_spine.csv, data/master_dataset.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

DATA = Path(__file__).parent / "data"

SOURCES = {
    "horror": DATA / "horror_movies.csv",
    "community_horror": DATA / "community" / "tmdb_horror_ids.csv",
    "community_scifi": DATA / "community_scifi" / "tmdb_scifi_ids.csv",
    "community_mystery": DATA / "community_mystery" / "tmdb_mystery_ids.csv",
    "community_thriller": DATA / "community_thriller" / "tmdb_thriller_ids.csv",
}

SPINE_FIELDS = [
    "id",
    "title",
    "original_title",
    "year",
    "original_language",
    "poster_path",
    "vote_count",
    "vote_average",
    "popularity",
    "adult",
    "sources",
]


def build_spine() -> dict[str, dict]:
    records: dict[str, dict] = {}
    source_tags: dict[str, set[str]] = {}

    for name, path in SOURCES.items():
        if not path.exists():
            print(f"  SKIP {name}: {path} not found")
            continue
        n = 0
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            r = csv.DictReader(f)
            for row in r:
                i = row.get("id", "").strip()
                if not i:
                    continue
                n += 1
                source_tags.setdefault(i, set()).add(name)
                rec = records.get(i, {})
                for field in [
                    "title",
                    "original_title",
                    "year",
                    "original_language",
                    "poster_path",
                    "vote_count",
                    "vote_average",
                    "popularity",
                    "adult",
                ]:
                    val = row.get(field, "")
                    if val and not rec.get(field):
                        rec[field] = val
                records[i] = rec
        print(f"  {name}: {n:,} rows read")

    print(f"\nUnion total: {len(records):,} ids")

    out_path = DATA / "master_spine.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SPINE_FIELDS)
        w.writeheader()
        for i, rec in sorted(records.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
            row = {k: rec.get(k, "") for k in SPINE_FIELDS if k != "id" and k != "sources"}
            row["id"] = i
            row["sources"] = "|".join(sorted(source_tags.get(i, [])))
            w.writerow(row)
    print(f"Escrito {out_path} ({len(records):,} filas)")

    multi = sum(1 for s in source_tags.values() if len(s) > 1)
    print(f"ids en mas de una fuente (overlap de genero): {multi:,}\n")
    return records


GENRE_SUFFIXES = ["", "_scifi", "_mystery", "_thriller"]


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def merge_categorical(
    base_name: str, label_col: str, score_col: str, extra_cols: list[str], prefix: str
) -> tuple[dict[str, dict], int, int]:
    """Highest score wins across genre variants; flags disagreement."""
    by_id: dict[str, list[dict]] = {}
    for suf in GENRE_SUFFIXES:
        rows = load_csv(DATA / f"{base_name}{suf}.csv")
        for row in rows:
            by_id.setdefault(row["id"], []).append(row)

    out: dict[str, dict] = {}
    n_conflict = 0
    for i, variants in by_id.items():
        best = max(variants, key=lambda r: _fnum(r.get(score_col)))
        labels = {r.get(label_col) for r in variants}
        conflict = 1 if len(labels) > 1 else 0
        if conflict:
            n_conflict += 1
        rec = {
            f"{prefix}_{label_col}": best.get(label_col, ""),
            f"{prefix}_{score_col}": best.get(score_col, ""),
            f"{prefix}_conflict": conflict,
        }
        for c in extra_cols:
            rec[f"{prefix}_{c}"] = best.get(c, "")
        out[i] = rec
    return out, len(by_id), n_conflict


def _fnum(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("-inf")


def merge_continuous(
    base_name: str, value_cols: list[str], extra_cols: list[str], prefix: str
) -> tuple[dict[str, dict], int]:
    """Average numeric columns across genre variants; copy extra (non-numeric) cols as-is."""
    by_id: dict[str, list[dict]] = {}
    for suf in GENRE_SUFFIXES:
        rows = load_csv(DATA / f"{base_name}{suf}.csv")
        for row in rows:
            by_id.setdefault(row["id"], []).append(row)

    out: dict[str, dict] = {}
    for i, variants in by_id.items():
        rec = {}
        for c in value_cols:
            vals = [_fnum(r.get(c)) for r in variants if _fnum(r.get(c)) != float("-inf")]
            rec[f"{prefix}_{c}"] = round(sum(vals) / len(vals), 6) if vals else ""
        for c in extra_cols:
            rec[f"{prefix}_{c}"] = variants[0].get(c, "")
        out[i] = rec
    return out, len(by_id)


def merge_single_file(path: Path, value_cols: list[str], prefix: str) -> dict[str, dict]:
    """SigLIP files: one file already covers the full corpus, no genre-variant merge needed."""
    out = {}
    for row in load_csv(path):
        out[row["id"]] = {f"{prefix}_{c}": row.get(c, "") for c in value_cols}
    return out


def phase2a_semantic() -> list[dict]:
    print("=== Fase 2a: color + CLIP/SigLIP semantico ===\n")

    color, n = merge_continuous(
        "posters",
        [
            "brightness",
            "dark_share",
            "saturation",
            "red_share",
            "band_red",
            "band_warm",
            "band_green",
            "band_blue",
            "band_purple",
            "band_dark",
        ],
        ["palette", "palette_share"],
        "color",
    )
    print(f"color: {n:,} ids (avg entre variantes de genero)")

    census, n, conf = merge_categorical(
        "census", "label", "score", ["is_animal", "is_creature"], "clip_census"
    )
    print(f"clip_census: {n:,} ids, {conf:,} con label en conflicto entre generos")

    fear_axis, n = merge_continuous("fear_axis", ["axis"], ["register", "genre"], "clip_fear_axis")
    print(f"clip_fear_axis: {n:,} ids")

    typography, n = merge_continuous("typography", ["axis"], ["register"], "clip_typography")
    print(f"clip_typography: {n:,} ids")

    medium, n, conf = merge_categorical("medium", "painted", "p_painted", [], "clip_medium")
    print(f"clip_medium: {n:,} ids, {conf:,} con label en conflicto entre generos")

    attributes, n = merge_continuous(
        "attributes",
        [
            "symmetry",
            "neg_space",
            "complexity",
            "mass_y",
            "mass_x",
            "text_area",
            "text_y",
            "text_regions",
            "text_x",
            "text_top",
            "text_w",
            "text_h",
            "align_score",
            "thirds_dist",
            "n_blocks",
            "balance",
            "harmony",
            "diagonal_score",
            "pyramid_shift",
        ],
        [],
        "clip_attributes",
    )
    print(f"clip_attributes: {n:,} ids")

    siglip_census = merge_single_file(
        DATA / "siglip_census.csv", ["label", "score"], "siglip_census"
    )
    print(f"siglip_census: {len(siglip_census):,} ids (archivo unico, sin variantes)")

    siglip_fear_axis = merge_single_file(
        DATA / "siglip_fear_axis.csv", ["axis"], "siglip_fear_axis"
    )
    print(f"siglip_fear_axis: {len(siglip_fear_axis):,} ids")

    siglip_typography = merge_single_file(
        DATA / "siglip_typography.csv", ["axis"], "siglip_typography"
    )
    print(f"siglip_typography: {len(siglip_typography):,} ids")

    siglip_genre = (
        merge_single_file(
            DATA / "siglip_genre_classifier.csv",
            [c for c in load_csv(DATA / "siglip_genre_classifier.csv")[0].keys() if c != "id"],
            "siglip_genre",
        )
        if (DATA / "siglip_genre_classifier.csv").exists()
        else {}
    )
    print(f"siglip_genre_classifier: {len(siglip_genre):,} ids")

    return [
        color,
        census,
        fear_axis,
        typography,
        medium,
        attributes,
        siglip_census,
        siglip_fear_axis,
        siglip_typography,
        siglip_genre,
    ]


def dedup_prefer_ok(
    rows: list[dict], status_col: str = "status", ok_val: str = "ok"
) -> dict[str, dict]:
    """Keep one row per id: prefer status==ok_val, else last occurrence (most recent run)."""
    out: dict[str, dict] = {}
    for row in rows:
        i = row["id"]
        if i not in out or row.get(status_col) == ok_val:
            out[i] = row
    return out


def phase2b_ocr_language() -> list[dict]:
    print("=== Fase 2b: OCR + idioma + validacion de titulo ===\n")

    # OCR text: merge base/scifi/mystery/thriller/alllang genre-coverage variants.
    # Deterministic OCR on the same image -- prefer the variant with more words read
    # (a more complete extraction), not an average (can't average text strings).
    ocr_by_id: dict[str, list[dict]] = {}
    for suf in ["", "_scifi", "_mystery", "_thriller", "_alllang"]:
        for row in load_csv(DATA / f"poster_ocr_rek_text{suf}.csv"):
            ocr_by_id.setdefault(row["id"], []).append(row)
    ocr = {}
    for i, variants in ocr_by_id.items():
        best = max(
            variants,
            key=lambda r: _fnum(r.get("n_words"))
            if _fnum(r.get("n_words")) != float("-inf")
            else -1,
        )
        ocr[i] = {
            "ocr_full_text": best.get("full_ocr", ""),
            "ocr_n_words": best.get("n_words", ""),
            "ocr_n_lines": best.get("n_lines", ""),
            "ocr_mean_conf": best.get("mean_conf", ""),
        }
    print(f"ocr (Rekognition DetectText, agregado por poster): {len(ocr):,} ids")

    # Comprehend language on the DetectText OCR text specifically (matches the OCR above).
    # easyocr/textract rows kept separately as cross-check columns, only on the core corpus.
    comp_by_id: dict[str, list[dict]] = {}
    comp_easyocr: dict[str, str] = {}
    comp_textract: dict[str, str] = {}
    for suf in ["", "_scifi", "_mystery", "_thriller", "_alllang"]:
        for row in load_csv(DATA / f"ocr_comprehend{suf}.csv"):
            src = row.get("source", "")
            # Genre-coverage files stamp their own source, e.g.
            # "detecttext_scifi" not "detecttext" -- same signal, just
            # scoped so a merge bug like this one is easier to catch (a
            # bare "detecttext" match here silently dropped every scifi/
            # mystery/thriller row, since none of them used that exact
            # string).
            if src == "detecttext" or src.startswith("detecttext_"):
                comp_by_id.setdefault(row["id"], []).append(row)
            elif src == "easyocr":
                comp_easyocr[row["id"]] = row.get("lang_code", "")
            elif src == "textract":
                comp_textract[row["id"]] = row.get("lang_code", "")
    comprehend = {}
    conf = 0
    for i, variants in comp_by_id.items():
        best = max(variants, key=lambda r: _fnum(r.get("lang_score")))
        langs = {r.get("lang_code") for r in variants}
        is_conflict = 1 if len(langs) > 1 else 0
        conf += is_conflict
        comprehend[i] = {
            "ocr_lang_code": best.get("lang_code", ""),
            "ocr_lang_score": best.get("lang_score", ""),
            "ocr_lang_conflict": is_conflict,
            "ocr_sentiment": best.get("sentiment", ""),
            "ocr_lang_code_easyocr": comp_easyocr.get(i, ""),
            "ocr_lang_code_textract": comp_textract.get(i, ""),
        }
    print(
        f"comprehend (idioma, fuente detecttext): {len(comprehend):,} ids, {conf:,} con idioma en conflicto entre generos"
    )

    # Text <-> title overlap + Translate result. Base file only covered the
    # horror-only corpus -- merge base/scifi/mystery/thriller genre-coverage
    # variants the same way as the OCR merge above (identical schema, verified).
    # First file with the id wins (deterministic given the same poster/OCR input).
    title_match = {}
    for suf in ["", "_scifi", "_mystery", "_thriller"]:
        p = DATA / "qa" / f"poster_title_match{suf}.csv"
        if not p.exists():
            continue
        for row in load_csv(p):
            if row["id"] not in title_match:
                title_match[row["id"]] = {
                    f"title_match_{k}": v for k, v in row.items() if k != "id"
                }
    print(f"title_match (overlap OCR<->titulo + Translate): {len(title_match):,} ids")

    # Nova Pro full-corpus check of Rekognition's OCR accuracy (not the same as content-match).
    qa_rows = dedup_prefer_ok(load_csv(DATA / "qa" / "qa_title_ocr.csv"))
    title_ocr_qa = {
        i: {
            "title_ocr_qa_verdict": r.get("verdict", ""),
            "title_ocr_qa_reason": r.get("reason", ""),
        }
        for i, r in qa_rows.items()
    }
    print(f"title_ocr_qa (Nova Pro, precision del OCR, corpus completo): {len(title_ocr_qa):,} ids")

    # Small-sample vision review of poster<->film content match (Nova, then Sonnet 2nd opinion).
    nova_drift = {}
    for row in load_csv(DATA / "qa" / "poster_title_match_drift_review.csv"):
        nova_drift[row["id"]] = {
            "nova_drift_verdict": row.get("verdict", ""),
            "nova_drift_reason": row.get("reason", ""),
        }
    print(f"nova_drift (revision visual poster<->pelicula, muestra): {len(nova_drift):,} ids")

    sonnet_drift = {}
    for row in load_csv(DATA / "qa" / "poster_title_match_drift_review_sonnet.csv"):
        sonnet_drift[row["id"]] = {
            "sonnet_drift_verdict": row.get("verdict", ""),
            "sonnet_drift_reason": row.get("reason", ""),
        }
    print(f"sonnet_drift (segunda opinion sobre los mismatch de Nova): {len(sonnet_drift):,} ids")

    return [ocr, comprehend, title_match, title_ocr_qa, nova_drift, sonnet_drift]


def phase2c_perceptual() -> list[dict]:
    print(
        "=== Fase 2c: scoring perceptual (pyiqa, NIMA, LAION aesthetic, depth, saliency, pose) ===\n"
    )

    def direct_join(path: Path, prefix: str) -> dict[str, dict]:
        out = {}
        for row in load_csv(path):
            out[row["id"]] = {f"{prefix}_{k}": v for k, v in row.items() if k != "id"}
        return out

    iqa = direct_join(DATA / "qa" / "iqa_multi.csv", "iqa")
    print(f"iqa (CLIP-IQA/MUSIQ/BRISQUE): {len(iqa):,} ids")

    nima = direct_join(DATA / "qa" / "nima_result.csv", "nima")
    print(f"nima: {len(nima):,} ids")

    aesthetic = direct_join(DATA / "qa" / "aesthetic_result.csv", "laion_aesthetic")
    print(f"laion_aesthetic: {len(aesthetic):,} ids")

    depth = direct_join(DATA / "qa" / "depth_score.csv", "depth")
    print(f"depth (MiDaS): {len(depth):,} ids")

    saliency = direct_join(DATA / "qa" / "saliency_score.csv", "saliency")
    print(f"saliency (MSI-Net): {len(saliency):,} ids")

    pose = direct_join(DATA / "qa" / "pose_score.csv", "pose")
    print(f"pose (ViTPose): {len(pose):,} ids")

    return [iqa, nima, aesthetic, depth, saliency, pose]


def summarize_boxes(path: Path, prefix: str) -> dict[str, dict]:
    """JSON id -> [{label, score, box}]. Summarize instead of exploding rows: count +
    top label by score (useful for a wide per-poster table; full boxes stay in the JSON)."""
    import json

    if not path.exists():
        return {}
    data = json.load(path.open())
    out = {}
    for i, boxes in data.items():
        if not boxes:
            out[i] = {f"{prefix}_n": 0, f"{prefix}_top_label": "", f"{prefix}_top_score": ""}
            continue
        top = max(boxes, key=lambda b: b.get("score", 0))
        out[i] = {
            f"{prefix}_n": len(boxes),
            f"{prefix}_top_label": top.get("label", ""),
            f"{prefix}_top_score": top.get("score", ""),
        }
    return out


def phase2d_enrichment() -> list[dict]:
    print("=== Fase 2d: enrichment (Rekognition, Nova, celebrities, criatura/arma) ===\n")

    # Base file only covered the horror-only corpus -- merge the scifi/mystery/
    # thriller sidecar (identical schema, run via rekognition_enrich.py
    # --ids-file /tmp/rek_pending_ids.txt --sidecar rekognition_scifi_mystery_
    # thriller.csv, 2026-08-19, 68,805 rows). First file with the id wins --
    # same fix as celebrities below, same root cause (single-file direct_join
    # never extended when scifi/mystery/thriller enrichment was added).
    rekognition = {}
    for p in [DATA / "rekognition.csv", DATA / "rekognition_scifi_mystery_thriller.csv"]:
        if not p.exists():
            continue
        for row in load_csv(p):
            if row["id"] not in rekognition:
                rekognition[row["id"]] = {
                    (k if k.startswith("rek_") else f"rek_{k}"): v
                    for k, v in row.items()
                    if k != "id"
                }
    print(f"rekognition: {len(rekognition):,} ids")
    # nova_lite_enrich.csv is a 14-row backfill fully contained in rekognition.csv already -- skip.

    # Base file only covered the horror-only corpus -- merge base/scifi/mystery/thriller
    # genre-coverage variants (identical schema, verified). First file with the id wins.
    nova = {}
    for p in [
        DATA / "qa" / "nova_enrich" / "nova_enrich.csv",
        DATA / "qa" / "nova_enrich_scifi" / "nova_enrich_scifi.csv",
        DATA / "qa" / "nova_enrich_mystery" / "nova_enrich_mystery.csv",
        DATA / "qa" / "nova_enrich_thriller" / "nova_enrich_thriller.csv",
    ]:
        if not p.exists():
            continue
        for row in load_csv(p):
            if row["id"] not in nova:
                nova[row["id"]] = {f"nova_{k}": v for k, v in row.items() if k != "id"}
    print(f"nova_enrich: {len(nova):,} ids")

    # Base file only covers ids RecognizeCelebrities has run on so far (originally
    # horror-only, faces>0); celebrities_scifi_mystery_thriller.csv is the same
    # scan extended to scifi/mystery/thriller's faces>0 ids not already covered
    # via horror overlap. First file with the id wins (disjoint by construction --
    # the second file's --ids-file excluded anything already in the first).
    celeb = {}
    for p in [DATA / "celebrities.csv", DATA / "celebrities_scifi_mystery_thriller.csv"]:
        if not p.exists():
            continue
        for row in load_csv(p):
            if row["id"] not in celeb:
                celeb[row["id"]] = {f"celeb_{k}": v for k, v in row.items() if k != "id"}
    print(f"celebrities: {len(celeb):,} ids")

    # Base file only covered the horror-only corpus -- merge base/scifi/mystery/thriller
    # genre-coverage variants (identical schema, verified). First file with the id wins.
    faces = {}
    for suf in ["", "_scifi", "_mystery", "_thriller"]:
        p = DATA / f"faces_v2{suf}.csv"
        if not p.exists():
            continue
        for row in load_csv(p):
            if row["id"] not in faces:
                faces[row["id"]] = {f"faces_{k}": v for k, v in row.items() if k != "id"}
    print(f"faces_v2 (YuNet): {len(faces):,} ids")

    creature = summarize_boxes(DATA / "creature_boxes.json", "creature_owlv2")
    print(f"creature_boxes (OWLv2): {len(creature):,} ids")

    creature_dino = summarize_boxes(DATA / "creature_boxes_dino.json", "creature_dino")
    print(f"creature_boxes_dino (Grounding-DINO cross-check): {len(creature_dino):,} ids")

    weapon = summarize_boxes(DATA / "weapon_boxes.json", "weapon_owlv2")
    print(f"weapon_boxes (OWLv2): {len(weapon):,} ids")

    weapon_dino = summarize_boxes(DATA / "weapon_boxes_dino.json", "weapon_dino")
    print(f"weapon_boxes_dino (Grounding-DINO cross-check): {len(weapon_dino):,} ids")

    return [rekognition, nova, celeb, faces, creature, creature_dino, weapon, weapon_dino]


def write_master(spine: dict[str, dict], groups: list[dict]) -> None:
    all_cols: set[str] = set()
    for g in groups:
        for rec in g.values():
            all_cols |= set(rec.keys())
    all_cols = sorted(all_cols)

    out_path = DATA / "master_dataset.csv"
    fieldnames = SPINE_FIELDS + all_cols
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for i, spine_rec in sorted(spine.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
            row = dict.fromkeys(fieldnames, "")
            row["id"] = i
            for k in SPINE_FIELDS:
                if k != "id":
                    row[k] = spine_rec.get(k, "")
            for g in groups:
                if i in g:
                    row.update(g[i])
            w.writerow(row)
    print(f"\nEscrito {out_path} ({len(spine):,} filas, {len(fieldnames)} columnas)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spine-only", action="store_true")
    args = ap.parse_args()

    build_spine()
    if not args.spine_only:
        spine = {row["id"]: row for row in load_csv(DATA / "master_spine.csv")}
        groups = phase2a_semantic()
        print()
        groups += phase2b_ocr_language()
        print()
        groups += phase2c_perceptual()
        print()
        groups += phase2d_enrichment()
        write_master(spine, groups)


if __name__ == "__main__":
    main()
