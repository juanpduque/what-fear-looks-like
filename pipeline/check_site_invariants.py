#!/usr/bin/env python3
"""Check that every published site data file matches the canonical corpus.

  python3 check_site_invariants.py   # exit 1 on any violation
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from corpus import canonical_ids  # noqa: E402

ROOT = HERE.parent
DATA = HERE / "data"
SITE = ROOT / "site"
SITE_DATA = SITE / "data"


def _js_payload(path: Path, marker: str):
    text = path.read_text(encoding="utf-8")
    start = text.index(marker) + len(marker)
    return json.loads(text[start:].rstrip().rstrip(";")), text.split("\n", 1)[0]


def _read_ids(path: Path) -> set[int]:
    if not path.is_file():
        return set()
    return {int(x) for x in path.read_text().split() if x.strip().isdigit()}


def main() -> int:
    keep = canonical_ids()
    n = len(keep)
    errors: list[str] = []
    max_year = date.today().year

    excluded: set[int] = set()
    for p in DATA.glob("excluded_*.csv"):
        if p.name.endswith("_review.csv"):
            continue
        with p.open(newline="", encoding="utf-8") as f:
            excluded |= {int(r["id"]) for r in csv.DictReader(f) if r.get("id", "").isdigit()}
    no_poster = _read_ids(DATA / "qa" / "no_poster" / "no_poster_ids.txt")
    if keep & excluded:
        errors.append(f"canonical contiene {len(keep & excluded)} ids excluidos")
    if keep & no_poster:
        errors.append(f"canonical contiene {len(keep & no_poster)} ids no_poster")

    rows, head = _js_payload(SITE_DATA / "explorer.js", "const POSTERS=")
    ids = [r[7] for r in rows]
    if len(ids) != len(set(ids)):
        errors.append("explorer.js tiene ids duplicados")
    if set(ids) != keep:
        errors.append(
            f"explorer.js != canonical (faltan {len(keep - set(ids))}, sobran {len(set(ids) - keep)})"
        )
    if f"n={n}" not in head:
        errors.append(f"explorer.js header sin n={n}: {head}")
    bad_years = [r for r in rows if not (1900 <= r[0] <= max_year)]
    if bad_years:
        errors.append(f"explorer.js {len(bad_years)} años fuera de 1900–{max_year}")
    assets = SITE / "assets" / "posters"
    missing_art = [r[7] for r in rows if not r[2] and not (assets / f"{r[7]}.jpg").exists()]
    if missing_art:
        errors.append(f"explorer.js {len(missing_art)} filas sin path ni asset local")

    lookup, head = _js_payload(SITE_DATA / "lookup.js", "window.LOOKUP=")
    if {int(k) for k in lookup} != keep:
        errors.append(f"lookup.js keys != canonical ({len(lookup)} vs {n})")
    if f"n={n}" not in head:
        errors.append(f"lookup.js header sin n={n}")

    series_txt = (SITE_DATA / "series.js").read_text(encoding="utf-8")
    m = re.search(r"n=([\d,]+) posters", series_txt)
    if not m or int(m.group(1).replace(",", "")) != n:
        errors.append(f"series.js n={m.group(1) if m else '?'} != {n}")

    for name, marker in (
        ("pose.js", "window.POSE="),
        ("creature_boxes.js", "window.CREATURE_BOXES="),
        ("weapon_boxes.js", "window.WEAPON_BOXES="),
    ):
        p = SITE_DATA / name
        if not p.exists():
            continue
        data, _ = _js_payload(p, marker)
        extra = {int(k) for k in data} - keep
        if extra:
            errors.append(f"{name} tiene {len(extra)} ids fuera del corpus")
        # weapon_boxes lists every scored poster (empty list = no weapon).
        if name == "weapon_boxes.js":
            missing = keep - {int(k) for k in data}
            if missing:
                errors.append(f"{name} le faltan {len(missing)} ids del corpus")

    for name in ("hue_river.json", "census_decade.json", "faces_v2_decade.json"):
        decs = [int(r["decade"]) for r in json.loads((DATA / name).read_text())]
        if any(d < 1900 or d > max_year for d in decs):
            errors.append(f"{name} con décadas fuera de rango: {sorted(decs)}")

    essay = SITE / "src" / "charts" / "essay.js"
    if essay.exists():
        cited = {int(x) for x in re.findall(r"\[(\d+),\s*\"", essay.read_text(encoding="utf-8"))}
        out = sorted(cited - keep)
        if out:
            errors.append(f"essay.js cita {len(out)} películas fuera del corpus: {out}")

    from sync_front_n import check_front_n
    errors += [f"copy: {i}" for i in check_front_n(n)]

    stray = sorted(p.name for p in SITE_DATA.iterdir() if ".bak" in p.name)
    if stray:
        errors.append(f"backups dentro de site/data: {stray}")

    if errors:
        print(f"FALLA ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: n={n:,} igual en explorer, lookup, series, globals y copy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
