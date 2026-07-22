#!/usr/bin/env python3
"""Enrich posters with AWS Rekognition signals (labels, moderation, faces, colors).

Complements local CLIP / YuNet / palette — does not replace them. Per image:
  DetectLabels (+ Image Properties) + DetectModerationLabels + DetectFaces
≈ 3 Group-2 API calls (~$0.003/poster → ~$80 for 27.6k).

  python3 rekognition_enrich.py --ids 578,948 --merge-lookup
  python3 rekognition_enrich.py --sample 200
  python3 rekognition_enrich.py --live-lookup          # full corpus, resume

Requires: aws configure, boto3. Region: us-east-1.

Outputs: data/rekognition.csv
"""
from __future__ import annotations

import argparse, json, time
from pathlib import Path

import boto3
import pandas as pd
from botocore.exceptions import ClientError

DATA = Path(__file__).parent / "data"
OUT = DATA / "rekognition.csv"
POSTERS = DATA / "posters"
REGION = "us-east-1"

WEAPON = {
    "weapon", "blade", "knife", "dagger", "sword", "gun", "handgun", "rifle",
    "axe", "hatchet", "bow", "arrow", "spear", "mace", "chainsaw",
}
ANIMAL = {
    "animal", "shark", "fish", "sea life", "insect", "bird", "dog", "cat",
    "wolf", "bear", "snake", "spider", "bat", "crow", "raven", "great white shark",
}
PERSON = {"person", "human", "man", "woman", "boy", "girl", "adult", "child", "face", "baby"}
WATER = {"water", "ocean", "sea", "lake", "beach", "wave", "underwater"}
FIRE = {"fire", "flame", "smoke", "explosion"}
SILHOUETTE = {"silhouette"}


def _client():
    return boto3.client("rekognition", region_name=REGION)


def _flag(labels, vocab):
    best = 0.0
    for name, conf in labels:
        if name.lower() in vocab:
            best = max(best, conf)
    return round(best, 4)


def _mod_score(mods, *names):
    want = {n.lower() for n in names}
    best = 0.0
    for name, conf in mods:
        if name.lower() in want:
            best = max(best, conf)
    return round(best, 4)


def analyze(client, path: Path) -> dict:
    data = path.read_bytes()
    if len(data) > 5_000_000:
        raise ValueError("image >5MB")

    # 1) Labels + image properties
    lab = client.detect_labels(
        Image={"Bytes": data},
        MaxLabels=20,
        MinConfidence=50,
        Features=["GENERAL_LABELS", "IMAGE_PROPERTIES"],
        Settings={"ImageProperties": {"MaxDominantColors": 5}},
    )
    labels = [(l["Name"], float(l["Confidence"]) / 100.0) for l in lab.get("Labels", [])]
    n_boxes = sum(len(l.get("Instances") or []) for l in lab.get("Labels", []))
    ip = lab.get("ImageProperties") or {}
    q = ip.get("Quality") or {}
    colors = ip.get("DominantColors") or []
    color_s = "|".join(
        f"{c.get('HexCode', '')}:{round(float(c.get('PixelPercent', 0)), 1)}"
        for c in colors[:5]
    )
    label_s = "|".join(f"{n}:{c:.2f}" for n, c in labels[:10])

    # 2) Moderation
    mod = client.detect_moderation_labels(Image={"Bytes": data}, MinConfidence=40)
    mods = [
        (m["Name"], float(m["Confidence"]) / 100.0)
        for m in mod.get("ModerationLabels", [])
    ]
    mod_s = "|".join(f"{n}:{c:.2f}" for n, c in mods[:8])

    # 3) Faces (often empty on painted posters — still useful on photo sheets)
    faces = client.detect_faces(Image={"Bytes": data}, Attributes=["ALL"])
    details = faces.get("FaceDetails") or []
    emotion = gender = ""
    age_lo = age_hi = -1
    if details:
        # largest face by bounding box area
        details = sorted(
            details,
            key=lambda f: f["BoundingBox"]["Width"] * f["BoundingBox"]["Height"],
            reverse=True,
        )
        f0 = details[0]
        emos = sorted(f0.get("Emotions") or [], key=lambda e: -e["Confidence"])
        if emos:
            emotion = f"{emos[0]['Type']}:{emos[0]['Confidence']/100:.2f}"
        gender = (f0.get("Gender") or {}).get("Value") or ""
        ar = f0.get("AgeRange") or {}
        age_lo = int(ar.get("Low", -1))
        age_hi = int(ar.get("High", -1))

    top_n, top_c = (labels[0][0], labels[0][1]) if labels else ("", 0.0)
    return dict(
        rek_labels=label_s,
        rek_top=top_n,
        rek_top_conf=round(top_c, 4),
        rek_weapon=_flag(labels, WEAPON),
        rek_animal=_flag(labels, ANIMAL),
        rek_person=_flag(labels, PERSON),
        rek_water=_flag(labels, WATER),
        rek_fire=_flag(labels, FIRE),
        rek_silhouette=_flag(labels, SILHOUETTE),
        rek_n_boxes=int(n_boxes),
        rek_bright=round(float(q.get("Brightness") or 0), 2),
        rek_sharp=round(float(q.get("Sharpness") or 0), 2),
        rek_contrast=round(float(q.get("Contrast") or 0), 2),
        rek_colors=color_s,
        rek_mod=mod_s,
        rek_violence=_mod_score(mods, "Violence", "Graphic Violence"),
        rek_mod_weapons=_mod_score(mods, "Weapons"),
        rek_gore=_mod_score(
            mods, "Visually Disturbing", "Blood & Gore", "Gore",
            "Emaciated Bodies", "Corpses", "Hanging",
        ),
        rek_n_faces=len(details),
        rek_emotion=emotion,
        rek_gender=gender,
        rek_age_lo=age_lo,
        rek_age_hi=age_hi,
    )


def decade_summary(df: pd.DataFrame) -> dict:
    """Share of posters with weapon/animal/violence flags by decade."""
    if df.empty or "year" not in df.columns:
        return {}
    d = df.copy()
    d["decade"] = (d["year"] // 10 * 10).astype(int)
    out = {}
    for dec, g in d.groupby("decade"):
        n = len(g)
        out[str(int(dec))] = {
            "n": n,
            "weapon": round(float((g.rek_weapon > 0.5).mean()), 4),
            "animal": round(float((g.rek_animal > 0.5).mean()), 4),
            "person": round(float((g.rek_person > 0.5).mean()), 4),
            "violence": round(float((g.rek_violence > 0.4).mean()), 4),
            "gore": round(float((g.rek_gore > 0.4).mean()), 4),
            "has_face": round(float((g.rek_n_faces > 0).mean()), 4),
            "silhouette": round(float((g.rek_silhouette > 0.5).mean()), 4),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument("--live-lookup", action="store_true")
    ap.add_argument("--merge-lookup", action="store_true",
                    help="rebuild lookup.js at the end")
    args = ap.parse_args()

    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    if args.ids:
        want = {int(x) for x in args.ids.split(",") if x.strip()}
        meta = meta[meta.id.isin(want)]
    elif args.sample:
        meta = meta.groupby(meta.year // 10 * 10, group_keys=False).apply(
            lambda g: g.sample(min(len(g), max(1, args.sample // 11)), random_state=42)
        )

    existing = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame()
    rows = {int(r["id"]): dict(r) for r in existing.to_dict("records")} if len(existing) else {}
    done = set(rows) if not args.ids else set()

    client = _client()
    t0 = time.time()
    n_new = 0
    for r in meta.itertuples(index=False):
        pid = int(r.id)
        if pid in done:
            continue
        path = POSTERS / f"{pid}.jpg"
        if not path.exists():
            continue
        try:
            feats = analyze(client, path)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            print(f"aws {pid}: {code} {e}", flush=True)
            if code in ("ThrottlingException", "ProvisionedThroughputExceededException"):
                time.sleep(2.0)
                try:
                    feats = analyze(client, path)
                except Exception as e2:
                    print(f"fail {pid}: {e2}", flush=True)
                    continue
            else:
                continue
        except Exception as e:
            print(f"fail {pid}: {e}", flush=True)
            continue

        row = dict(id=pid, year=int(r.year), title=str(r.title), **feats)
        rows[pid] = row
        n_new += 1
        if n_new % 10 == 0:
            rate = n_new / max(time.time() - t0, 1e-6)
            print(
                f"{n_new} new | {pid} {str(r.title)[:26]!r} "
                f"top={row['rek_top']!r} weap={row['rek_weapon']} "
                f"viol={row['rek_violence']} faces={row['rek_n_faces']} | {rate:.2f}/s",
                flush=True,
            )
        if n_new % args.save_every == 0:
            df = pd.DataFrame(rows.values())
            df.to_csv(OUT, index=False)
            (DATA / "rekognition_decade.json").write_text(
                json.dumps(decade_summary(df), indent=2), encoding="utf-8"
            )
            if args.live_lookup:
                import build_lookup
                build_lookup.main()

    df = pd.DataFrame(rows.values())
    df.to_csv(OUT, index=False)
    (DATA / "rekognition_decade.json").write_text(
        json.dumps(decade_summary(df), indent=2), encoding="utf-8"
    )
    print(f"wrote {OUT} ({len(df)} rows, {n_new} new, {time.time()-t0:.1f}s)")
    if args.merge_lookup or args.live_lookup:
        import build_lookup
        build_lookup.main()


if __name__ == "__main__":
    main()
