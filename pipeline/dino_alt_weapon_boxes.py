#!/usr/bin/env python3
"""Grounding DINO cross-check for OWLv2 weapon boxes on alternate sheets.

Measured covers have a Nova Pro verdict for every OWLv2 weapon box
(qa_creature_weapon_boxes.py); alternates do not. For weapons, OWLv2 boxes that
an independent Grounding DINO box overlaps (IoU >= 0.3) were ~71% correct vs
~59% overall in that QA, so export_poster_alts_geom.py only publishes
alternate weapon boxes DINO agrees with.

grounding_dino_boxes.py is keyed by integer id and reads {posters}/{id}.jpg,
so this stages each (id, file_path) alternate under a sequence number, then
maps DINO's output back:

  python3 dino_alt_weapon_boxes.py stage --work /tmp/alt_dino
  python3 grounding_dino_boxes.py --ids-file /tmp/alt_dino/ids.txt \\
      --posters-dir /tmp/alt_dino/posters --device mps \\
      --creature-out /tmp/alt_dino/creature.json --weapon-out /tmp/alt_dino/weapon.json
  python3 dino_alt_weapon_boxes.py merge --work /tmp/alt_dino --weapon /tmp/alt_dino/weapon.json

Writes data/qa/alts_dino_catalog/weapon_boxes_dino_alts.json
  {id: {file_path: [{label, score, box}]}}
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALTS_OWL = HERE.parent / "site" / "data" / "poster_alts_owl.json"
OUT = HERE / "data" / "qa" / "alts_dino_catalog" / "weapon_boxes_dino_alts.json"
TMDB = "https://image.tmdb.org/t/p/w780"
# Same floor the autopsy uses to draw weapon boxes; lower ones are never shown.
MIN_SCORE = 0.3


def stage(work: Path) -> None:
    owl = json.loads(ALTS_OWL.read_text(encoding="utf-8"))
    keys = sorted(
        {
            (pid, path)
            for pid, sheets in owl.items()
            for path, row in sheets.items()
            if any(b["score"] >= MIN_SCORE for b in row.get("w", []))
        }
    )
    posters = work / "posters"
    posters.mkdir(parents=True, exist_ok=True)
    (work / "index.json").write_text(json.dumps([list(k) for k in keys]), encoding="utf-8")
    (work / "ids.txt").write_text("".join(f"{n}\n" for n in range(len(keys))), encoding="utf-8")

    def fetch(n: int) -> bool:
        dst = posters / f"{n}.jpg"
        if dst.exists():
            return True
        for _ in range(3):
            try:
                urllib.request.urlretrieve(TMDB + keys[n][1], dst)
                return True
            except OSError:
                pass
        return False

    with ThreadPoolExecutor(16) as ex:
        ok = sum(ex.map(fetch, range(len(keys))))
    print(f"staged {len(keys):,} alternate sheets ({len(keys) - ok} downloads failed) in {work}")


def merge(work: Path, weapon_files: list[Path]) -> None:
    keys = json.loads((work / "index.json").read_text(encoding="utf-8"))
    out: dict[str, dict[str, list]] = {}
    for wf in weapon_files:
        for n, boxes in json.loads(wf.read_text(encoding="utf-8")).items():
            pid, path = keys[int(n)]
            out.setdefault(pid, {})[path] = boxes
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    n = sum(map(len, out.values()))
    print(f"wrote {OUT} sheets={n:,}/{len(keys):,}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stage")
    s.add_argument("--work", type=Path, required=True)
    m = sub.add_parser("merge")
    m.add_argument("--work", type=Path, required=True)
    m.add_argument(
        "--weapon", type=Path, nargs="+", required=True, help="DINO --weapon-out file(s)"
    )
    args = ap.parse_args()
    if args.cmd == "stage":
        stage(args.work)
    else:
        merge(args.work, args.weapon)


if __name__ == "__main__":
    main()
