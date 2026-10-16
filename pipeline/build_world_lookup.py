#!/usr/bin/env python3
"""Every non-English poster in the essay's world chart, openable in the autopsy.

The world chart (site/data/world.js, export_world_faces.py) counts 4,598
non-English horror posters from 2000–2026 in 12 languages. Each gets the same
LOOKUP record as the corpus (build_lookup.build_records) plus its MSI-Net map.
English films come from the corpus, which the autopsy already covers.

Under the chart, each language shows its most-voted films; those load with the
page. The rest load one language at a time when the reader asks for them.

The saliency maps (data/qa/saliency_world) are MSI-Net runs on the sheet
the pipeline measured (horror_movies.csv poster_path), so they describe the
same image as every other measure. The first run used TMDB's current poster;
the 2,427 films where that differs were rerun on the measured sheet.

  python3 build_world_lookup.py

Records also carry the layers the corpus loads from separate globals:
cboxes (OWLv2 creature boxes, world run in WORLD_CBOXES), wboxes (OWLv2 weapon boxes minus the ones Nova
Pro judged false positives, as build_site.py does, and the ones metric_images.py
says were measured on another file) and pose (pose.js row).

Writes:
  site/data/world_lookup.js   WORLD_EXAMPLES {lang: [id]} most-voted since 2000,
                              WORLD_INDEX    {lang: [id]} every chart poster, most-voted first,
                              WORLD_POSTERS  explorer rows (+ lang, original title) for the examples,
                              WORLD_LOOKUP   {id: LOOKUP record + cboxes, wboxes, pose}
  site/data/world/{lang}.js   WORLD_LANGS[lang] = {posters, lookup} for every chart poster
  site/saliency_world/{id}.webp
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import metric_images
from build_explorer import dominant_hex
from build_lookup import build_records
from build_site import GLOBAL_SRC, drop_nova_false_positives
from corpus import canonical_ids
from export_saliency_webp import to_webp
from export_world_faces import comparable_non_english

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SITE = HERE.parent / "site"
OUT = SITE / "data" / "world_lookup.js"
LANG_DIR = SITE / "data" / "world"
SAL_DIR = DATA / "qa" / "saliency_world"
SAL_OUT = SITE / "saliency_world"
WORLD_CBOXES = DATA / "qa" / "creature_boxes_world.json"
PER_LANG = 12
RECENT = (2000, 2026)


def world_langs() -> list[str]:
    text = (SITE / "data" / "world.js").read_text(encoding="utf-8")
    start = text.index("window.WORLD_FACES=") + len("window.WORLD_FACES=")
    return [r["lang"] for r in json.loads(text[start : text.index(";\n", start)])]


def js(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def main() -> None:
    movies = {}
    with (DATA / "horror_movies.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            movies[int(r["id"])] = r
    posters = {}
    with (DATA / "posters.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            posters.setdefault(int(r["id"]), r)
    faces, face_year = {}, {}
    with (DATA / "faces_v2.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            faces[int(r["id"])] = int(float(r["n_faces"] or 0))
            if r["year"]:
                face_year[int(r["id"])] = int(float(r["year"]))
    creatures = {}
    with (DATA / "census.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            creatures[int(r["id"])] = (r.get("label") or "").strip()
    has_map = {int(p.stem) for p in (SAL_DIR / "maps").glob("*.png")}

    def votes(pid: int) -> float:
        return float((movies.get(pid) or {}).get("vote_count") or 0)

    langs = {pid: "en" for pid in canonical_ids()}
    langs.update(comparable_non_english())
    pool: dict[str, list[tuple[float, int]]] = {}
    for pid, lang in langs.items():
        m, p = movies.get(pid), posters.get(pid)
        if not m or not p or not m.get("poster_path"):
            continue
        if not RECENT[0] <= int(float(p["year"])) <= RECENT[1]:
            continue
        if lang != "en" and pid not in has_map:
            continue
        pool.setdefault(lang, []).append((votes(pid), pid))

    examples = {
        lang: [pid for _, pid in sorted(pool.get(lang, []), reverse=True)[:PER_LANG]]
        for lang in world_langs()
    }
    world_ids = [pid for lang, ids in examples.items() if lang != "en" for pid in ids]

    # Same selection as export_world_faces.py: faces_v2 year in RECENT.
    chart: dict[str, list[int]] = {lang: [] for lang in world_langs() if lang != "en"}
    for pid, lang in langs.items():
        if lang in chart and RECENT[0] <= face_year.get(pid, 0) <= RECENT[1]:
            chart[lang].append(pid)
    for ids in chart.values():
        ids.sort(key=lambda pid: (-votes(pid), pid))

    def row(pid: int) -> list | None:
        m, p = movies.get(pid), posters.get(pid)
        if not m or not p or not m.get("poster_path"):
            return None
        out = [
            int(float(p["year"])),
            dominant_hex(p.get("palette")),
            m["poster_path"],
            p.get("title") or "",
            round(float(p["brightness"]), 1),
            faces.get(pid, 0),
            creatures.get(pid, ""),
            pid,
            langs[pid],
        ]
        # original title, when it differs: the grid's search matches either
        orig = (m.get("original_title") or "").strip()
        if orig and orig != out[3]:
            out.append(orig)
        return out

    all_ids = set(world_ids).union(*chart.values())
    lookup = build_records(all_ids, sal_paths=[SAL_DIR / "saliency_score.csv"])
    # The corpus OWLv2 run skipped these films (no local poster); the world run
    # used the measured sheets (owlv2_creature_boxes.py --creature-out WORLD_CBOXES).
    cboxes = json.loads((DATA / "creature_boxes.json").read_text(encoding="utf-8"))
    cboxes.update(json.loads(WORLD_CBOXES.read_text(encoding="utf-8")))
    wboxes = drop_nova_false_positives(
        json.loads((DATA / "weapon_boxes.json").read_text(encoding="utf-8"))
    )
    # Weapon boxes measured on a different file than posters/ has today (the
    # restored world posters, metric_images.py) would sit on the wrong sheet.
    ledger = metric_images.load()
    wrong = [
        pid
        for pid in all_ids
        if wboxes.get(str(pid))
        and ledger.get(pid, {}).get("weapon_boxes")
        and ledger[pid]["weapon_boxes"] != metric_images.file_sha(pid)
    ]
    for pid in wrong:
        wboxes.pop(str(pid))
    print(f"  weapon boxes dropped, measured on another file: {len(wrong)}")
    pose_js = (GLOBAL_SRC / "pose.js").read_text(encoding="utf-8")
    start = pose_js.index("window.POSE=") + len("window.POSE=")
    pose = json.loads(pose_js[start:].rstrip().rstrip(";"))
    for key, rec in lookup.items():
        if cboxes.get(key):
            rec["cboxes"] = cboxes[key]
        if wboxes.get(key):
            rec["wboxes"] = wboxes[key]
        if key in pose:
            rec["pose"] = pose[key]

    # A poster is openable when it has an explorer row and a LOOKUP record.
    openable = {pid for pid in all_ids if row(pid) and str(pid) in lookup}
    index = {lang: [pid for pid in ids if pid in openable] for lang, ids in chart.items()}

    SAL_OUT.mkdir(parents=True, exist_ok=True)
    maps = sorted(openable & has_map)
    keep = {f"{pid}.webp" for pid in maps}
    for stale in SAL_OUT.glob("*.webp"):
        if stale.name not in keep:
            stale.unlink()
    for pid in maps:
        (SAL_OUT / f"{pid}.webp").write_bytes(to_webp(SAL_DIR / "maps" / f"{pid}.png", 80))

    LANG_DIR.mkdir(parents=True, exist_ok=True)
    for stale in LANG_DIR.glob("*.js"):
        if stale.stem not in index:
            stale.unlink()
    for lang, ids in index.items():
        out = LANG_DIR / f"{lang}.js"
        data = {
            "posters": [row(pid) for pid in ids],
            "lookup": {str(pid): lookup[str(pid)] for pid in ids},
        }
        out.write_text(
            f"/* World chart posters, {lang} — pipeline/build_world_lookup.py */\n"
            f"(window.WORLD_LANGS=window.WORLD_LANGS||{{}})[{js(lang)}]={js(data)};\n",
            encoding="utf-8",
        )

    shown = [pid for pid in world_ids if pid in openable]
    OUT.write_text(
        "/* World horror posters for the autopsy — pipeline/build_world_lookup.py */\n"
        f"window.WORLD_EXAMPLES={js(examples)};\n"
        f"window.WORLD_INDEX={js(index)};\n"
        f"window.WORLD_POSTERS={js([row(pid) for pid in shown])};\n"
        f"window.WORLD_LOOKUP={js({str(pid): lookup[str(pid)] for pid in shown})};\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e3:.0f} kB), {len(maps):,} saliency maps")
    size = sum(f.stat().st_size for f in LANG_DIR.glob("*.js"))
    print(f"wrote {LANG_DIR}/*.js ({size / 1e6:.1f} MB)")
    for lang, ids in chart.items():
        ok = index[lang]
        recs = [lookup[str(pid)] for pid in ok]
        print(
            f"  {lang}: {len(ok):,} of {len(ids):,} openable,"
            f" saliency {sum(pid in has_map for pid in ok):,},"
            f" cboxes {sum('cboxes' in r for r in recs):,},"
            f" wboxes {sum('wboxes' in r for r in recs):,},"
            f" pose {sum('pose' in r for r in recs):,}"
        )
    missing = sorted(set().union(*chart.values()) - openable)
    if missing:
        print(f"  not openable ({len(missing)}): {missing[:20]}")


if __name__ == "__main__":
    main()
