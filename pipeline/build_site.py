#!/usr/bin/env python3
"""Rebuild every site data file from the canonical corpus (canonical_ids.txt).

  python3 build_corpus.py   # first, when criteria or TMDB metadata change
  python3 build_site.py

Steps: decade aggregates → series.js → explorer.js → lookup.js →
pose/creature/weapon box globals pruned to the corpus → front copy n →
check_site_invariants.py. Raw per-poster CSVs are only read.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from corpus import canonical_ids  # noqa: E402

DATA = HERE / "data"
SITE_DATA = HERE.parent / "site" / "data"
# Unpruned copies of id-keyed site globals that have no CSV builder here.
GLOBAL_SRC = DATA / "site_globals_full"
ID_GLOBALS = ["pose.js", "creature_boxes.js", "weapon_boxes.js"]


def prune_id_global(name: str, keep: frozenset[int]) -> None:
    dst = SITE_DATA / name
    src = GLOBAL_SRC / name
    if not src.exists():
        if not dst.exists():
            print(f"  aviso: falta {name}")
            return
        GLOBAL_SRC.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, src)
    text = src.read_text(encoding="utf-8")
    eq = text.index("={")
    head, body = text[:eq], text[eq + 1:].rstrip().rstrip(";")
    data = json.loads(body)
    kept = {k: v for k, v in data.items() if k.isdigit() and int(k) in keep}
    first_nl = head.find("\n")
    comment, decl = (head[:first_nl], head[first_nl + 1:]) if first_nl >= 0 else ("", head)
    note = f"/* {name} n={len(kept)} (canonical corpus; full set in pipeline/data/site_globals_full) */"
    dst.write_text(
        f"{note}\n{decl}={json.dumps(kept, ensure_ascii=False, separators=(',', ':'))};\n",
        encoding="utf-8",
    )
    print(f"  {name}: {len(data):,} -> {len(kept):,}")


def main() -> None:
    keep = canonical_ids()
    print(f"corpus canonico n={len(keep):,}")

    from apply_exclusions import (
        regen_attributes_decade,
        regen_census_decade,
        regen_faces_decade,
        regen_segmentation_decade,
        regen_typography_decade,
        regen_yearly_and_river,
    )
    print("\nagregados por decada...")
    regen_yearly_and_river(keep=keep)
    regen_attributes_decade(keep=keep)
    regen_census_decade(keep=keep)
    regen_typography_decade(keep=keep)
    regen_faces_decade(keep=keep)
    regen_segmentation_decade(keep=keep)

    print("\nseries.js...")
    from export_site_series import export
    export()

    print("\nexplorer.js...")
    from build_explorer import main as build_explorer
    build_explorer()

    print("\nlookup.js...")
    from build_lookup import main as build_lookup
    build_lookup()

    print("\nglobals por id...")
    for name in ID_GLOBALS:
        prune_id_global(name, keep)

    print("\nn del texto front...")
    from sync_front_n import check_front_n, sync_front_n
    n = len(keep)
    rep = sync_front_n(n)
    if rep.get("changed"):
        print(f"  {rep['stale']:,} -> {n:,} ({len(rep['files'])} archivos)")
    for issue in check_front_n(n):
        print(f"  aviso: {issue}")

    print("\ninvariantes...")
    from check_site_invariants import main as check
    if check() != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
