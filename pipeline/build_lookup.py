"""Build site/data/lookup.js — compact per-poster analysis for the search UI.

Merges posters / attributes / faces_v2 / census / typography / medium /
segmentation into one id-keyed object. Run after pipeline CSVs update:

  python3 build_lookup.py

Schema (LOOKUP[id]):
  t,y,path,L,dark,sat,red,pal,bands[6],faces,farea,nova_faces?,
  nova_creature?,nova_typo?,nova_title?,nova_ocr?,creature,cscore,
  typo,taxis,painted,comp{...},sem{...}?
  nova_* fields are Nova Pro QA (pipeline/data/qa/qa_*.csv); display only.
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


def clip_text(val, n=48):
    s = "" if val is None or (isinstance(val, float) and pd.isna(val)) else str(val).strip()
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


def load_qa_ok(path, cols):
    if not path.exists():
        return []
    qa = pd.read_csv(path, usecols=cols)
    if "status" in qa.columns:
        qa = qa[qa["status"] == "ok"]
    return qa.itertuples(index=False)


def parse_boxes(raw):
    """'x,y,w,h|x,y,w,h' (normalized) -> [[x,y,w,h], ...]."""
    if raw is None or str(raw) in ("", "nan"):
        return []
    boxes = []
    for part in str(raw).split("|"):
        bits = part.split(",")
        if len(bits) != 4:
            continue
        try:
            boxes.append([float(b) for b in bits])
        except ValueError:
            continue
    return boxes


def main():
    from corpus import canonical_ids
    post = pd.read_csv(DATA / "posters.csv")
    post = post[post.id.isin(canonical_ids())].drop_duplicates("id")
    attr = pd.read_csv(DATA / "attributes.csv").set_index("id")
    faces = pd.read_csv(DATA / "faces_v2.csv").set_index("id")
    census = pd.read_csv(DATA / "census.csv").set_index("id")
    typo = pd.read_csv(DATA / "typography.csv").set_index("id")
    medium = pd.read_csv(DATA / "medium.csv").set_index("id")
    seg = pd.read_csv(DATA / "segmentation.csv").set_index("id")
    rek_path = DATA / "rekognition.csv"
    rek = pd.read_csv(rek_path).set_index("id") if rek_path.exists() else None
    nova_faces: dict[int, int] = {}
    for row in load_qa_ok(DATA / "qa" / "qa_faces.csv", ["id", "status", "nova_n_faces"]):
        try:
            nova_faces[int(row.id)] = int(float(row.nova_n_faces))
        except (TypeError, ValueError):
            continue

    nova_creature: dict[int, str] = {}
    for row in load_qa_ok(DATA / "qa" / "qa_census.csv", ["id", "status", "nova_label"]):
        try:
            pid = int(row.id)
        except (TypeError, ValueError):
            continue
        lab = clip_text(row.nova_label, 32)
        if lab:
            nova_creature[pid] = lab

    nova_typo: dict[int, str] = {}
    for row in load_qa_ok(DATA / "qa" / "qa_typography.csv", ["id", "status", "nova_register"]):
        try:
            pid = int(row.id)
        except (TypeError, ValueError):
            continue
        reg = clip_text(row.nova_register, 16)
        if reg:
            nova_typo[pid] = reg

    nova_ocr: dict[int, tuple[str, str]] = {}
    ocr_ok = {"accurate", "inaccurate", "no_title_on_poster"}
    for row in load_qa_ok(
        DATA / "qa" / "qa_title_ocr.csv",
        ["id", "status", "nova_text", "verdict"],
    ):
        try:
            pid = int(row.id)
        except (TypeError, ValueError):
            continue
        verdict = clip_text(row.verdict, 24)
        if verdict not in ocr_ok:
            continue
        nova_ocr[pid] = (clip_text(row.nova_text), verdict)

    rek_boxes = {}
    rek_boxes_path = DATA / "rekognition_face_boxes.csv"
    if rek_boxes_path.exists():
        rb = pd.read_csv(rek_boxes_path)
        if "error" in rb.columns:
            rb = rb[rb["error"].isna() | (rb["error"].astype(str) == "")]
        for row in rb.itertuples(index=False):
            boxes = parse_boxes(row.face_boxes)
            if boxes:
                rek_boxes[int(row.id)] = boxes

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
        nf = nova_faces.get(i)
        if nf is not None:
            rec["nova_faces"] = nf
        nc = nova_creature.get(i)
        if nc is not None:
            rec["nova_creature"] = nc
        nt = nova_typo.get(i)
        if nt is not None:
            rec["nova_typo"] = nt
        ocr = nova_ocr.get(i)
        if ocr is not None:
            title, verdict = ocr
            rec["nova_ocr"] = verdict
            if title:
                rec["nova_title"] = title
        if f is not None:
            fboxes = parse_boxes(getattr(f, "face_boxes", None))
            if fboxes:
                rec["fboxes"] = fboxes
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
            rboxes = rek_boxes.get(i)
            if rboxes:
                rec["rek"]["fboxes"] = rboxes
        lookup[str(i)] = rec

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(lookup, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(
        f"/* Per-poster analysis lookup n={len(lookup)} - pipeline/build_lookup.py */\n"
        f"window.LOOKUP={payload};\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT} ({len(lookup)} posters, {OUT.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
