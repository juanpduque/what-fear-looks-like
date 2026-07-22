"""Build site/data/lookup.js — compact per-poster analysis for the search UI.

Merges posters / attributes / faces_v2 / census / typography / medium /
segmentation into one id-keyed object. Run after pipeline CSVs update:

  python3 build_lookup.py

Schema (LOOKUP[id]):
  t,y,path,L,dark,sat,red,pal,bands[6],faces,farea,creature,cscore,
  typo,taxis,painted,comp{...},sem{...}?
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT.parent / "site" / "data" / "lookup.js"

SEG_KEYS = [
    "clip_blood", "clip_weapon", "clip_shadow", "clip_fire",
    "clip_bone_skull", "clip_smoke_fog", "clip_night_sky",
]
BANDS = ["band_red", "band_warm", "band_green", "band_blue", "band_purple", "band_dark"]


def r(x, n=2):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def parse_list(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return []
    if isinstance(val, list):
        return val
    s = str(val).strip()
    if not s:
        return []
    try:
        out = ast.literal_eval(s)
        return list(out) if isinstance(out, (list, tuple)) else []
    except (ValueError, SyntaxError):
        return []


def main():
    post = pd.read_csv(DATA / "posters.csv")
    attr = pd.read_csv(DATA / "attributes.csv").set_index("id")
    faces = pd.read_csv(DATA / "faces_v2.csv").set_index("id")
    census = pd.read_csv(DATA / "census.csv").set_index("id")
    typo = pd.read_csv(DATA / "typography.csv").set_index("id")
    medium = pd.read_csv(DATA / "medium.csv").set_index("id")
    seg = pd.read_csv(DATA / "segmentation.csv").set_index("id")
    rek_path = DATA / "rekognition.csv"
    rek = pd.read_csv(rek_path).set_index("id") if rek_path.exists() else None

    lookup = {}
    for row in post.itertuples(index=False):
        i = int(row.id)
        a = attr.loc[i] if i in attr.index else None
        f = faces.loc[i] if i in faces.index else None
        c = census.loc[i] if i in census.index else None
        t = typo.loc[i] if i in typo.index else None
        m = medium.loc[i] if i in medium.index else None
        s = seg.loc[i] if i in seg.index else None
        rk = rek.loc[i] if rek is not None and i in rek.index else None

        # title / year / tmdb path live in explorer.js POSTERS
        rec = {
            "L": r(row.brightness, 1),
            "dark": r(row.dark_share),
            "sat": r(row.saturation),
            "red": r(row.red_share),
            "pal": [str(x) for x in parse_list(row.palette)[:5]],
            "bands": [r(getattr(row, b)) or 0 for b in BANDS],
            "faces": int(f.n_faces) if f is not None else 0,
            "farea": r(f.face_area) if f is not None else 0,
        }
        if c is not None and pd.notna(c.label) and str(c.label):
            rec["creature"] = str(c.label)
            rec["cscore"] = r(c.score, 2)
        if t is not None:
            rec["typo"] = str(t.register)
            rec["taxis"] = r(t.axis, 2)
        if m is not None:
            rec["painted"] = r(m.p_painted, 2)
        if a is not None:
            rec["comp"] = {
                "sym": r(a.symmetry),
                "neg": r(a.neg_space),
                "cx": r(a.complexity),
                "mx": r(a.mass_x),
                "my": r(a.mass_y),
                "txt": r(a.text_area),
                "ty": r(a.text_y),
                "tx": r(getattr(a, "text_x", None)),
                "tt": r(getattr(a, "text_top", None)),
                "tw": r(getattr(a, "text_w", None)),
                "th": r(getattr(a, "text_h", None)),
                "align": r(a.align_score),
                "thirds": r(a.thirds_dist),
                "bal": r(a.balance),
                "harm": r(a.harmony),
                "diag": r(a.diagonal_score),
                "pyr": r(a.pyramid_shift),
            }
        if s is not None:
            sem = {}
            for k in SEG_KEYS:
                v = r(getattr(s, k), 2)
                if v and v > 0:
                    sem[k.replace("clip_", "")] = v
            if sem:
                rec["sem"] = sem
        if rk is not None:
            flags = []
            for key, lab in (
                ("rek_weapon", "weapon"),
                ("rek_animal", "animal"),
                ("rek_person", "person"),
                ("rek_water", "water"),
                ("rek_fire", "fire"),
                ("rek_silhouette", "silhouette"),
            ):
                v = r(getattr(rk, key, None), 2)
                if v and v >= 0.5:
                    flags.append(lab)
            rec["rek"] = {
                "top": str(rk.rek_top) if pd.notna(rk.rek_top) else "",
                "topc": r(rk.rek_top_conf, 2),
                "labels": str(rk.rek_labels) if pd.notna(rk.rek_labels) else "",
                "flags": flags,
                "viol": r(rk.rek_violence, 2),
                "gore": r(rk.rek_gore, 2),
                "faces": int(rk.rek_n_faces) if pd.notna(rk.rek_n_faces) else 0,
                "emo": str(rk.rek_emotion) if pd.notna(rk.rek_emotion) and str(rk.rek_emotion) else "",
                "bright": r(rk.rek_bright, 1),
                "colors": str(rk.rek_colors) if pd.notna(rk.rek_colors) else "",
            }
        lookup[str(i)] = rec

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(lookup, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(
        f"/* Per-poster analysis lookup n={len(lookup)} - pipeline/build_lookup.py */\n"
        f"const LOOKUP={payload};\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT} ({len(lookup)} posters, {OUT.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
