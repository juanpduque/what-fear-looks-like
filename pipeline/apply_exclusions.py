#!/usr/bin/env python3
"""
Aplica todos los CSV data/excluded_*.csv al dataset ya calculado y regenera
cada agregado que alimenta el sitio.

Listas actuales:
  - excluded_animation.csv — genero oficial TMDB "Animation"
  - excluded_music.csv     — genero oficial TMDB "Music"
  - excluded_non_english.csv — original_language != "en" (tipografia/OCR)

No se excluyen "TV Movie" (telefilms): son peliculas unitarias para TV,
no series; se quedan en el corpus a proposito.

No re-analiza imagenes ni re-embebe nada: todas las metricas por poster ya
existen en CSV/NPZ, esto solo filtra filas y vuelve a correr el groupby de
cada script (mismo codigo que fear_pipeline.py / multi_analyze.py /
clip_census.py / clip_typography_axis.py / faces_v2.py / segmentation.py).

  python3 apply_exclusions.py

Outputs actualizados: posters.csv, attributes.csv, attributes_partial.csv,
faces_v2.csv, faces_v2_partial.csv, census.csv, typography.csv, medium.csv,
segmentation.csv, segmentation_partial.csv, clip_embeddings.npz,
rekognition.csv, title_boxes*.csv, yearly.json, hue_river.json,
darkness_curve.png, attributes_decade.json, census_decade.json,
typography_decade.json, faces_v2_decade.json, segmentation_decade.json,
y site/data/series.js (series de graficas del ensayo).
"""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"
sys.path.insert(0, str(Path(__file__).parent))
from export_site_series import export as export_site_series


def load_exclude_ids():
    ids = set()
    for path in sorted(DATA.glob("excluded_*.csv")):
        if path.name.endswith("_review.csv"):
            continue
        part = set(pd.read_csv(path, usecols=["id"]).id)
        print(f"  {path.name}: {len(part):,} ids")
        ids |= part
    print(f"excluyendo {len(ids):,} ids en total")
    return ids


def filter_csv(path, exclude_ids):
    if not path.exists():
        return
    d = pd.read_csv(path)
    if "id" not in d.columns:
        return
    before = len(d)
    d = d[~d.id.isin(exclude_ids)]
    d.to_csv(path, index=False)
    print(f"  {path.name}: {before:,} -> {len(d):,}")


def filter_npz(path, exclude_ids):
    if not path.exists():
        return
    z = np.load(path)
    ids, vecs = z["ids"], z["vecs"]
    keep = ~np.isin(ids, list(exclude_ids))
    before = len(ids)
    np.savez_compressed(path, ids=ids[keep], vecs=vecs[keep])
    print(f"  {path.name}: {before:,} -> {keep.sum():,}")


# ---------------------------------------------------------------------------
# regeneracion de agregados -- mismo codigo que cada script fuente
# ---------------------------------------------------------------------------

def regen_yearly_and_river():
    """fear_pipeline.py: yearly.json, hue_river.json, darkness_curve.png"""
    res = pd.read_csv(DATA / "posters.csv")
    yearly = (res.groupby("year")
                 .agg(n=("id", "count"), brightness=("brightness", "mean"),
                      dark_share=("dark_share", "mean"),
                      saturation=("saturation", "mean"),
                      red_share=("red_share", "mean"))
                 .round(4).reset_index())
    yearly.to_json(DATA / "yearly.json", orient="records")

    res["decade"] = (res.year // 10) * 10
    band_cols = ["band_red", "band_warm", "band_green", "band_blue",
                 "band_purple", "band_dark"]
    river = res.groupby("decade")[band_cols].mean().round(4)
    river["n"] = res.groupby("decade").size()
    river.reset_index().to_json(DATA / "hue_river.json", orient="records")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 5), facecolor="#0a0a0c")
        ax.set_facecolor("#0a0a0c")
        roll = yearly.set_index("year").brightness.rolling(5, min_periods=2).mean()
        ax.plot(roll.index, roll.values, color="#e5a00d", lw=2.5)
        ax.scatter(yearly.year, yearly.brightness, s=8, color="#e5a00d", alpha=.25)
        ax.set_title("The Darkness Curve — mean poster brightness (L*), 5yr rolling",
                     color="#e8e4da")
        ax.tick_params(colors="#9a958a")
        for sp in ax.spines.values(): sp.set_color("#2a2a30")
        fig.savefig(DATA / "darkness_curve.png", dpi=150, bbox_inches="tight")
    except ImportError:
        print("matplotlib no instalado -- se omite darkness_curve.png")
    print("regenerado: yearly.json, hue_river.json, darkness_curve.png")


def regen_attributes_decade():
    """multi_analyze.py"""
    p = DATA / "attributes.csv"
    if not p.exists() or not len(pd.read_csv(p)):
        return
    d = pd.read_csv(p).drop_duplicates("id")
    d["decade"] = (d.year // 10) * 10
    cols = [c for c in d.columns if c not in ("id", "year", "decade")]
    SENTINEL_COLS = {"align_score", "thirds_dist", "balance", "harmony"}
    masked = d[cols].copy()
    for c in SENTINEL_COLS & set(cols):
        masked[c] = masked[c].where(masked[c] >= 0)
    agg = masked.groupby(d["decade"])[cols].mean().round(4)
    agg["n"] = d.groupby("decade").size()
    agg.reset_index().to_json(DATA / "attributes_decade.json", orient="records")
    print("regenerado: attributes_decade.json")


def regen_census_decade(exclude_ids):
    """clip_census.py -- census.csv ya viene filtrado, solo re-agrupa"""
    p = DATA / "census.csv"
    if not p.exists():
        return
    df = pd.read_csv(p)
    df = df[~df.id.isin(exclude_ids)]
    df["decade"] = (df.year // 10) * 10
    shares = (df.groupby(["decade", "label"]).size()
                .unstack(fill_value=0)
                .pipe(lambda x: x.div(x.sum(1), axis=0)).round(4))
    shares.reset_index().to_json(DATA / "census_decade.json", orient="records")
    print("regenerado: census_decade.json")


def regen_typography_decade(exclude_ids):
    """clip_typography_axis.py"""
    p = DATA / "typography.csv"
    if not p.exists():
        return
    REGISTERS = ["ornate", "decorative", "standard", "clean", "minimal"]
    df = pd.read_csv(p)
    df = df[~df.id.isin(exclude_ids)]
    d = df[(df.year >= 1920) & (df.year <= 2029)].copy()
    d["decade"] = (d.year // 10) * 10
    sh = (d.groupby(["decade", "register"]).size().unstack(fill_value=0)
            .reindex(columns=REGISTERS, fill_value=0))
    share = sh.div(sh.sum(1), axis=0).round(4)
    mean_axis = d.groupby("decade")["axis"].mean().round(5)
    n = sh.sum(1)
    out = []
    for dec in share.index:
        row = {"decade": int(dec), "n": int(n[dec]), "mean_axis": float(mean_axis[dec])}
        for reg in REGISTERS:
            row[reg] = float(share.loc[dec, reg])
        out.append(row)
    (DATA / "typography_decade.json").write_text(json.dumps(out))
    print("regenerado: typography_decade.json")


def regen_faces_decade():
    """faces_v2.py"""
    p = DATA / "faces_v2.csv"
    if not p.exists():
        return
    d = pd.read_csv(p).drop_duplicates("id")
    d["decade"] = (d.year // 10) * 10
    agg = d.groupby("decade").agg(n=("id", "count"),
                                  mean_faces=("n_faces", "mean"),
                                  pct_with_face=("n_faces", lambda s: (s > 0).mean()),
                                  face_area=("face_area", "mean")).round(3)
    agg.reset_index().to_json(DATA / "faces_v2_decade.json", orient="records")
    print("regenerado: faces_v2_decade.json")


def regen_segmentation_decade():
    """segmentation.py"""
    p = DATA / "segmentation.csv"
    if not p.exists():
        return
    d = pd.read_csv(p).drop_duplicates("id")
    d["decade"] = (d.year // 10) * 10
    cols = [c for c in d.columns if c not in ("id", "year", "decade")]
    agg = d.groupby("decade")[cols].mean().round(4)
    agg["n"] = d.groupby("decade").size()
    agg.reset_index().to_json(DATA / "segmentation_decade.json", orient="records")
    print("regenerado: segmentation_decade.json")


def main():
    exclude_ids = load_exclude_ids()

    print("\nfiltrando CSV/NPZ por-poster...")
    for name in ["posters.csv", "attributes.csv", "attributes_partial.csv",
                 "faces_v2.csv", "faces_v2_partial.csv", "census.csv",
                 "typography.csv", "medium.csv", "segmentation.csv",
                 "segmentation_partial.csv", "rekognition.csv",
                 "title_boxes.csv", "title_boxes_rekognition.csv"]:
        filter_csv(DATA / name, exclude_ids)
    filter_npz(DATA / "clip_embeddings.npz", exclude_ids)

    print("\nregenerando agregados...")
    regen_yearly_and_river()
    regen_attributes_decade()
    regen_census_decade(exclude_ids)
    regen_typography_decade(exclude_ids)
    regen_faces_decade()
    regen_segmentation_decade()

    print("\nexportando series del sitio...")
    export_site_series()
    try:
        from build_explorer import main as build_explorer
        print("\nexportando explorer.js...")
        build_explorer()
    except Exception as e:
        print(f"aviso: no se pudo regenerar explorer.js ({e})")
    print("\nLISTO.")


if __name__ == "__main__":
    main()
