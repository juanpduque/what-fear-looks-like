#!/usr/bin/env python3
"""Example posters for the essay's world chart, openable in the autopsy.

For each language in site/data/world.js (export_world_faces.py), picks the
most-voted TMDB films from 2000–2026. English examples come from the corpus,
which the autopsy already covers. Non-English examples get the same LOOKUP
records as the corpus (build_lookup.build_records) plus their MSI-Net map.

Only films whose TMDB poster today is the sheet the pipeline measured are
eligible: the saliency maps (data/qa/saliency_world, run on today's TMDB
poster) must describe the same image as every other measure.

  python3 build_world_lookup.py

Records also carry the layers the corpus loads from separate globals:
cboxes (OWLv2 creature boxes, world run in WORLD_CBOXES), wboxes (OWLv2 weapon boxes minus the ones Nova
Pro judged false positives, as build_site.py does) and pose (pose.js row).

Writes:
  site/data/world_lookup.js   WORLD_EXAMPLES {lang: [id]},
                              WORLD_POSTERS  explorer rows (+ lang) for non-English ids,
                              WORLD_LOOKUP   {id: LOOKUP record + cboxes, wboxes, pose}
  site/saliency_world/{id}.webp
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

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
SAL_DIR = DATA / "qa" / "saliency_world"
SAL_OUT = SITE / "saliency_world"
TMDB = DATA / "qa" / "tmdb_details" / "tmdb_details.jsonl"
WORLD_CBOXES = DATA / "qa" / "creature_boxes_world.json"
PER_LANG = 12
RECENT = (2000, 2026)


def world_langs() -> list[str]:
    text = (SITE / "data" / "world.js").read_text(encoding="utf-8")
    start = text.index("window.WORLD_FACES=") + len("window.WORLD_FACES=")
    return [r["lang"] for r in json.loads(text[start : text.index(";\n", start)])]


def main() -> None:
    movies = {}
    with (DATA / "horror_movies.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            movies[int(r["id"])] = r
    current = {}
    for line in TMDB.open(encoding="utf-8"):
        rec = json.loads(line)
        current[int(rec["id"])] = rec.get("poster_path")
    posters = {}
    with (DATA / "posters.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            posters.setdefault(int(r["id"]), r)
    faces = {}
    with (DATA / "faces_v2.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            faces[int(r["id"])] = int(float(r["n_faces"] or 0))
    creatures = {}
    with (DATA / "census.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            creatures[int(r["id"])] = (r.get("label") or "").strip()
    has_map = {int(p.stem) for p in (SAL_DIR / "maps").glob("*.png")}

    langs = {pid: "en" for pid in canonical_ids()}
    langs.update(comparable_non_english())
    pool: dict[str, list[tuple[float, int]]] = {}
    for pid, lang in langs.items():
        m, p = movies.get(pid), posters.get(pid)
        if not m or not p or not m.get("poster_path"):
            continue
        if not RECENT[0] <= int(float(p["year"])) <= RECENT[1]:
            continue
        if lang != "en" and (m["poster_path"] != current.get(pid) or pid not in has_map):
            continue
        pool.setdefault(lang, []).append((float(m.get("vote_count") or 0), pid))

    examples = {
        lang: [pid for _, pid in sorted(pool.get(lang, []), reverse=True)[:PER_LANG]]
        for lang in world_langs()
    }
    world_ids = [pid for lang, ids in examples.items() if lang != "en" for pid in ids]

    rows = []
    for pid in world_ids:
        p = posters[pid]
        rows.append(
            [
                int(float(p["year"])),
                dominant_hex(p.get("palette")),
                movies[pid]["poster_path"],
                p.get("title") or "",
                round(float(p["brightness"]), 1),
                faces.get(pid, 0),
                creatures.get(pid, ""),
                pid,
                langs[pid],
            ]
        )
    lookup = build_records(set(world_ids), sal_paths=[SAL_DIR / "saliency_score.csv"])
    # The corpus OWLv2 run skipped these films (no local poster); the world run
    # used the measured sheets (owlv2_creature_boxes.py --creature-out WORLD_CBOXES).
    cboxes = json.loads((DATA / "creature_boxes.json").read_text(encoding="utf-8"))
    cboxes.update(json.loads(WORLD_CBOXES.read_text(encoding="utf-8")))
    wboxes = drop_nova_false_positives(
        json.loads((DATA / "weapon_boxes.json").read_text(encoding="utf-8"))
    )
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

    SAL_OUT.mkdir(parents=True, exist_ok=True)
    keep = {f"{pid}.webp" for pid in world_ids}
    for stale in SAL_OUT.glob("*.webp"):
        if stale.name not in keep:
            stale.unlink()
    for pid in world_ids:
        (SAL_OUT / f"{pid}.webp").write_bytes(to_webp(SAL_DIR / "maps" / f"{pid}.png", 80))

    def js(v) -> str:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

    OUT.write_text(
        "/* World horror examples for the autopsy — pipeline/build_world_lookup.py */\n"
        f"window.WORLD_EXAMPLES={js(examples)};\n"
        f"window.WORLD_POSTERS={js(rows)};\n"
        f"window.WORLD_LOOKUP={js(lookup)};\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e3:.0f} kB), {len(world_ids)} saliency maps")
    for layer in ("cboxes", "wboxes", "pose"):
        print(f"  {layer}: {sum(layer in rec for rec in lookup.values())} of {len(lookup)}")
    for lang, ids in examples.items():
        titles = [posters[pid]["title"] for pid in ids]
        print(f"  {lang}: {', '.join(titles)}")


if __name__ == "__main__":
    main()
