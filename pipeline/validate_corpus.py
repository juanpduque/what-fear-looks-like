#!/usr/bin/env python3
"""
Corpus integrity gate for What Fear Looks Like.

Capa 1 (fail hard): membresia, alineacion de metricas core, n publicado
(series/lookup/explorer + texto front/README), JPG legible y portrait
(one-sheet). Capas 2–3 (soft/warn): identidad IMDb/runtime (backlog =
features sin tt; cortos sin tt solo informativo) y artwork/drift → CSV
en --out-dir.

  python3 validate_corpus.py                 # solo capa 1 (CI / post-ingest)
  python3 validate_corpus.py --layers 1,2,3  # health completo
  python3 validate_corpus.py --layers 2,3 --out-dir data/qa
  python3 validate_corpus.py --strict-soft   # exit 2 si hay warns en 2–3
  python3 validate_corpus.py --fix-front    # si el texto front tiene n stale → sync

No llama APIs: reutiliza artefactos locales (imdb_ids, drift, horror_movies, match CSVs).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SITE = HERE.parent / "site"
DEFAULT_QA = DATA / "qa"

from sync_front_n import check_front_n, sync_front_n  # noqa: E402

CORE_CSVS = [
    "attributes.csv",
    "faces_v2.csv",
    "census.csv",
    "typography.csv",
    "medium.csv",
    "segmentation.csv",
]
IMDB_TT_RE = re.compile(r"^tt\d+$")
SERIES_N_RE = re.compile(r"n=([\d,]+)\s+posters")
LOOKUP_N_RE = re.compile(r"n=(\d+)")
SHORT_RUNTIME = 40  # titleType==short OR runtimeMinutes <= 40


class HardFail(Exception):
    """Capa 1 assertion failure."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def load_exclude_ids() -> set[int]:
    ids: set[int] = set()
    for path in sorted(DATA.glob("excluded_*.csv")):
        if path.name.endswith("_review.csv"):
            continue
        part = pd.read_csv(path, usecols=["id"])["id"].astype(int)
        ids |= set(part)
    return ids


def load_posters() -> pd.DataFrame:
    path = DATA / "posters.csv"
    if not path.exists():
        raise HardFail(f"falta {path}")
    d = pd.read_csv(path)
    for col in ("id", "title", "year"):
        if col not in d.columns:
            raise HardFail(f"posters.csv sin columna {col}")
    d["id"] = d["id"].astype(int)
    d["year"] = pd.to_numeric(d["year"], errors="coerce")
    return d


def load_id_set(csv_name: str) -> set[int]:
    path = DATA / csv_name
    if not path.exists():
        raise HardFail(f"falta {path}")
    return set(pd.read_csv(path, usecols=["id"])["id"].astype(int))


def write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def warn(msg: str, warnings: list[str]) -> None:
    line = f"[warn] {msg}"
    print(line)
    warnings.append(line)


def info(msg: str) -> None:
    print(f"[info] {msg}")


def ok(msg: str) -> None:
    print(f"[ok]   {msg}")


# ---------------------------------------------------------------------------
# capa 1 — fail hard
# ---------------------------------------------------------------------------

def layer1(posters: pd.DataFrame) -> int:
    """Assert structural integrity. Returns corpus n. Raises HardFail."""
    print("\n=== CAPA 1 (fail hard) ===")
    n = len(posters)
    if n == 0:
        raise HardFail("posters.csv vacio")

    if posters["id"].isna().any():
        raise HardFail("posters.csv tiene id NaN")
    dup = posters["id"][posters["id"].duplicated()]
    if len(dup):
        raise HardFail(f"ids duplicados en posters.csv: {dup.nunique():,}")

    excl = load_exclude_ids()
    leaks = set(posters["id"]) & excl
    if leaks:
        sample = sorted(leaks)[:12]
        raise HardFail(
            f"{len(leaks):,} ids de excluded_* siguen en posters.csv "
            f"(ej. {sample}). Corre: python3 apply_exclusions.py"
        )
    ok(f"membresia: 0 leaks / {len(excl):,} excluded ids")

    undated = int((posters["year"] == 9999).sum())
    bad_year = posters[
        posters["year"].isna()
        | ((posters["year"] != 9999) & ((posters["year"] < 1890) | (posters["year"] > 2035)))
    ]
    if len(bad_year):
        raise HardFail(
            f"{len(bad_year):,} years fuera de rango "
            f"(esperado 1890–2035 o 9999); ej. ids {bad_year['id'].head(8).tolist()}"
        )
    ok(f"years ok (undated/9999={undated:,})")

    post_ids = set(posters["id"])
    for name in CORE_CSVS:
        ids = load_id_set(name)
        miss = post_ids - ids
        extra = ids - post_ids
        if miss or extra:
            raise HardFail(
                f"{name}: miss={len(miss):,} extra={len(extra):,} "
                f"(posters={n:,}, file={len(ids):,})"
            )
        ok(f"{name}: {len(ids):,} alineado")

    emb_path = DATA / "clip_embeddings.npz"
    if not emb_path.exists():
        raise HardFail(f"falta {emb_path}")
    z = np.load(emb_path)
    emb_ids = set(int(x) for x in z["ids"])
    miss = post_ids - emb_ids
    extra = emb_ids - post_ids
    if miss or extra:
        raise HardFail(
            f"clip_embeddings.npz: miss={len(miss):,} extra={len(extra):,}"
        )
    ok(f"clip_embeddings.npz: {len(emb_ids):,} alineado")

    # published n
    series = SITE / "data" / "series.js"
    if not series.exists():
        raise HardFail(f"falta {series}")
    header = "\n".join(series.read_text(encoding="utf-8").splitlines()[:5])
    m = SERIES_N_RE.search(header)
    if not m:
        raise HardFail(f"no pude parsear n= en {series}")
    series_n = int(m.group(1).replace(",", ""))
    if series_n != n:
        raise HardFail(f"series.js n={series_n:,} != posters n={n:,}")
    ok(f"series.js n={series_n:,}")

    lookup = SITE / "data" / "lookup.js"
    if lookup.exists():
        first = lookup.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        lm = LOOKUP_N_RE.search(first)
        if lm and int(lm.group(1)) != n:
            raise HardFail(f"lookup.js n={int(lm.group(1)):,} != posters n={n:,}")
        if lm:
            ok(f"lookup.js n={int(lm.group(1)):,}")

    explorer = SITE / "data" / "explorer.js"
    if explorer.exists():
        first = explorer.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        em = LOOKUP_N_RE.search(first)
        if em and int(em.group(1)) != n:
            raise HardFail(f"explorer.js n={int(em.group(1)):,} != posters n={n:,}")
        if em:
            ok(f"explorer.js n={int(em.group(1)):,}")

    # front copy / README published n (i18n, index, ui)
    front_issues = check_front_n(n)
    if front_issues:
        raise HardFail(
            "texto front n != corpus:\n  - "
            + "\n  - ".join(front_issues)
            + "\ncorre: python3 sync_front_n.py --fix  (o validate_corpus.py --fix-front)"
        )
    ok(f"texto front n={n:,} alineado (index/i18n/README)")

    # JPG existence + open + portrait-only (one-sheet)
    posters_dir = DATA / "posters"
    miss_jpg: list[int] = []
    corrupt: list[tuple[int, str]] = []
    landscape: list[tuple[int, int, int]] = []
    for pid in posters["id"]:
        path = posters_dir / f"{int(pid)}.jpg"
        if not path.exists():
            miss_jpg.append(int(pid))
            continue
        try:
            with Image.open(path) as im:
                w, h = im.size
                im.verify()
            if w >= h:
                landscape.append((int(pid), int(w), int(h)))
        except Exception as e:  # noqa: BLE001 — collect all corrupt
            corrupt.append((int(pid), str(e)))
    if miss_jpg:
        raise HardFail(f"{len(miss_jpg):,} JPG faltantes (ej. {miss_jpg[:8]})")
    if corrupt:
        raise HardFail(
            f"{len(corrupt):,} JPG corruptos "
            f"(ej. {corrupt[0][0]}: {corrupt[0][1]})"
        )
    if landscape:
        sample = landscape[:8]
        raise HardFail(
            f"{len(landscape):,} JPG landscape/square en corpus "
            f"(one-sheet debe ser portrait; ej. {sample}). "
            f"Añade a excluded_landscape.csv y corre apply_exclusions.py"
        )
    ok(f"JPG locales: {n:,} presentes, legibles y portrait")

    ok(f"CAPA 1 PASS — corpus n={n:,}")
    return n


# ---------------------------------------------------------------------------
# capa 2 — identidad (soft)
# ---------------------------------------------------------------------------

def layer2(posters: pd.DataFrame, out_dir: Path, warnings: list[str]) -> None:
    print("\n=== CAPA 2 (identidad, soft) ===")
    print(
        f"[info] politica: backlog IMDb = features "
        f"(runtime>{SHORT_RUNTIME}); cortos sin tt no son warn"
    )
    meta = posters[["id", "title", "year"]].copy()
    n = len(meta)
    runtime = _runtime_frame()

    imdb_path = DATA / "imdb_ids.csv"
    if not imdb_path.exists():
        warn(f"falta {imdb_path.name} — skip IMDb checks", warnings)
    else:
        imdb = pd.read_csv(imdb_path)
        imdb["id"] = imdb["id"].astype(int)
        imdb["imdb_id"] = imdb["imdb_id"].astype(str).str.strip()
        imdb["tt_ok"] = imdb["imdb_id"].map(lambda s: bool(IMDB_TT_RE.match(s)))
        # one row per id (prefer valid tt)
        imdb = imdb.sort_values("tt_ok", ascending=False).drop_duplicates("id")

        m = meta.merge(imdb[["id", "imdb_id", "tt_ok"]], on="id", how="left")
        m["tt_ok"] = m["tt_ok"].fillna(False)
        if runtime is not None:
            m = m.merge(runtime, on="id", how="left")
        else:
            m["runtime"] = np.nan

        missing = m[~m["tt_ok"]].copy()
        write_csv(
            out_dir / "missing_imdb_id.csv",
            missing[["id", "title", "year", "runtime", "imdb_id"]],
        )

        # Feature backlog only (tt == imdb_id). Shorts without tt are expected noise.
        feat_miss = missing[
            missing["runtime"].notna() & (missing["runtime"] > SHORT_RUNTIME)
        ]
        short_miss = missing[
            missing["runtime"].notna()
            & (missing["runtime"] > 0)
            & (missing["runtime"] <= SHORT_RUNTIME)
        ]
        unk_miss = missing[missing["runtime"].isna() | (missing["runtime"] <= 0)]

        write_csv(
            out_dir / "missing_imdb_id_features.csv",
            feat_miss[["id", "title", "year", "runtime", "imdb_id"]],
        )
        write_csv(
            out_dir / "missing_imdb_id_shorts.csv",
            short_miss[["id", "title", "year", "runtime", "imdb_id"]],
        )

        n_feat = int(
            (
                m["runtime"].notna() & (m["runtime"] > SHORT_RUNTIME)
            ).sum()
        )
        n_feat_ok = int(
            (
                m["tt_ok"]
                & m["runtime"].notna()
                & (m["runtime"] > SHORT_RUNTIME)
            ).sum()
        )
        if n_feat:
            pct = 100.0 * len(feat_miss) / n_feat
            warn(
                f"capa 2: {len(feat_miss):,}/{n_feat:,} features "
                f"(runtime>{SHORT_RUNTIME}) sin imdb_id/tt… ({pct:.1f}%) "
                f"→ {out_dir / 'missing_imdb_id_features.csv'}",
                warnings,
            )
            ok(
                f"capa 2: features con tt {n_feat_ok:,}/{n_feat:,} "
                f"({100.0 * n_feat_ok / n_feat:.1f}%)"
            )
        elif runtime is None:
            info("capa 2: sin horror_movies.csv — no filtro features")
            warn(
                f"capa 2: {len(missing):,}/{n:,} sin tt (sin runtime para filtrar) "
                f"→ {out_dir / 'missing_imdb_id.csv'}",
                warnings,
            )

        info(
            f"capa 2: sin tt total={len(missing):,} "
            f"(features={len(feat_miss):,} shorts={len(short_miss):,} "
            f"runtime_unknown={len(unk_miss):,}) — solo features son warn"
        )

    # reuse match artifact CSVs if present (filter to corpus)
    post_ids = set(meta["id"])
    for kind in ("ambiguous", "miss"):
        src = DATA / f"imdb_basics_match_features_{kind}.csv"
        if not src.exists():
            info(f"capa 2: no hay {src.name} (skip)")
            continue
        d = pd.read_csv(src)
        d["id"] = d["id"].astype(int)
        in_corpus = d[d["id"].isin(post_ids)]
        dest = out_dir / f"imdb_match_features_{kind}.csv"
        write_csv(dest, in_corpus)
        if len(in_corpus):
            warn(
                f"capa 2: {len(in_corpus):,} match-{kind} en corpus → {dest}",
                warnings,
            )
        else:
            ok(f"capa 2: 0 match-{kind} en corpus ({src.name})")

    if runtime is not None:
        m = meta.merge(runtime, on="id", how="left")
        bad = m[m["runtime"].isna() | (m["runtime"] <= 0)].copy()
        bad["runtime_status"] = np.where(
            bad["runtime"].isna(), "missing", "zero"
        )
        write_csv(
            out_dir / "runtime_missing.csv",
            bad[["id", "title", "year", "runtime", "runtime_status"]],
        )
        # Runtime gaps block feature-vs-short classification — keep as warn.
        warn(
            f"capa 2: {len(bad):,}/{n:,} runtime missing/0 "
            f"(no se puede clasificar feature vs short) "
            f"→ {out_dir / 'runtime_missing.csv'}",
            warnings,
        )
        shorts = m[
            m["runtime"].notna()
            & (m["runtime"] > 0)
            & (m["runtime"] <= SHORT_RUNTIME)
        ]
        feats = m[m["runtime"].notna() & (m["runtime"] > SHORT_RUNTIME)]
        info(
            f"capa 2: features={len(feats):,} shorts(1–{SHORT_RUNTIME})="
            f"{len(shorts):,} (proxy; no es fail)"
        )
    else:
        warn("capa 2: falta horror_movies.csv — skip runtime", warnings)


def _runtime_frame() -> pd.DataFrame | None:
    path = DATA / "horror_movies.csv"
    if not path.exists():
        return None
    d = pd.read_csv(path, usecols=["id", "runtime"])
    d["id"] = d["id"].astype(int)
    d["runtime"] = pd.to_numeric(d["runtime"], errors="coerce")
    return d.drop_duplicates("id")


# ---------------------------------------------------------------------------
# capa 3 — artwork (soft)
# ---------------------------------------------------------------------------

def layer3(posters: pd.DataFrame, out_dir: Path, warnings: list[str]) -> None:
    print("\n=== CAPA 3 (artwork, soft) ===")
    meta = posters[["id", "title", "year"]].copy()
    post_ids = set(meta["id"])
    n = len(meta)

    # path coverage from horror_movies + backfill
    paths: dict[int, str] = {}
    hm = DATA / "horror_movies.csv"
    if hm.exists():
        for _, r in pd.read_csv(hm, usecols=["id", "poster_path"]).iterrows():
            pid = int(r["id"])
            p = str(r.get("poster_path") or "").strip()
            if p.startswith("/"):
                paths[pid] = p
    bf = DATA / "poster_paths_backfill.csv"
    if bf.exists():
        for _, r in pd.read_csv(bf).iterrows():
            try:
                pid = int(r["id"])
            except (TypeError, ValueError):
                continue
            p = str(r.get("poster_path") or "").strip()
            if pid in post_ids and pid not in paths and p.startswith("/"):
                paths[pid] = p

    missing_path = meta[~meta["id"].isin(paths)].copy()
    write_csv(out_dir / "missing_poster_path.csv", missing_path)
    if len(missing_path):
        warn(
            f"capa 3: {len(missing_path):,}/{n:,} sin poster_path "
            f"→ {out_dir / 'missing_poster_path.csv'}",
            warnings,
        )
    else:
        ok("capa 3: todos tienen poster_path (horror_movies/backfill)")

    # drift cache (no API)
    # mismatch = stored primary ≠ live TMDB primary → warn (artwork may be stale)
    # errors (not_found / no_poster) = TMDB id dead or poster cleared → info only;
    # local JPG + metrics can still be valid; remap/exclude is a separate backlog.
    drift_path = DATA / "poster_path_drift.csv"
    if drift_path.exists():
        drift = pd.read_csv(drift_path)
        drift["id"] = drift["id"].astype(int)
        drift = drift[drift["id"].isin(post_ids)]
        mismatch = drift[
            (drift["status"].astype(str) == "ok")
            & (drift["match"].astype(str).isin(["0", "0.0", "False", "false"]))
        ]
        errors = drift[drift["status"].astype(str) != "ok"]
        write_csv(out_dir / "poster_path_mismatch.csv", mismatch)
        write_csv(out_dir / "poster_path_drift_errors.csv", errors)
        checked = len(drift)
        n_nf = int((errors["status"].astype(str) == "not_found").sum()) if len(errors) else 0
        n_np = int((errors["status"].astype(str) == "no_poster").sum()) if len(errors) else 0
        n_other = len(errors) - n_nf - n_np
        if len(mismatch):
            warn(
                f"capa 3: drift mismatch={len(mismatch):,}/{checked:,} "
                f"(stored ≠ primary TMDB) → {out_dir / 'poster_path_mismatch.csv'}",
                warnings,
            )
        else:
            ok(f"capa 3: drift mismatch=0 (checked={checked:,})")
        if len(errors):
            info(
                f"capa 3: drift errors={len(errors):,} "
                f"(not_found={n_nf:,} no_poster={n_np:,}"
                f"{f' other={n_other:,}' if n_other else ''}) "
                f"— backlog remap/QA, no warn "
                f"→ {out_dir / 'poster_path_drift_errors.csv'}"
            )
        if checked < n:
            info(
                f"capa 3: drift solo cubre {checked:,}/{n:,} "
                f"(recorre validate_poster_paths.py para refrescar)"
            )
    else:
        info(
            "capa 3: no hay poster_path_drift.csv — "
            "opcional: validate_poster_paths.py para drift fresco"
        )

    # landscape / square JPGs in corpus
    posters_dir = DATA / "posters"
    rows = []
    for r in meta.itertuples(index=False):
        path = posters_dir / f"{int(r.id)}.jpg"
        if not path.exists():
            continue
        try:
            with Image.open(path) as im:
                w, h = im.size
            if w >= h:
                rows.append(
                    {
                        "id": int(r.id),
                        "title": r.title,
                        "year": r.year,
                        "width": w,
                        "height": h,
                        "aspect": round(w / max(h, 1), 4),
                    }
                )
        except Exception:  # noqa: BLE001
            continue
    land = pd.DataFrame(rows)
    write_csv(out_dir / "poster_landscape.csv", land)
    if len(land):
        warn(
            f"capa 3: {len(land):,} JPG landscape/square en corpus "
            f"→ {out_dir / 'poster_landscape.csv'}",
            warnings,
        )
    else:
        ok("capa 3: 0 landscape en corpus")

    qdir = DATA / "posters_quarantine_landscape"
    if qdir.exists():
        qids = sorted(
            int(p.stem) for p in qdir.glob("*.jpg") if p.stem.isdigit()
        )
        info(f"capa 3: quarantine dir tiene {len(qids)} jpg (informativo)")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_layers(s: str) -> set[int]:
    out: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        v = int(part)
        if v not in (1, 2, 3):
            raise SystemExit(f"capa invalida: {v} (usa 1,2,3)")
        out.add(v)
    if not out:
        raise SystemExit("--layers vacio")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--layers",
        default="1",
        help="capas a correr, comma-sep (default: 1). Ej: 1,2,3",
    )
    ap.add_argument(
        "--out-dir",
        default=str(DEFAULT_QA),
        help=f"CSV soft de capas 2–3 (default: {DEFAULT_QA})",
    )
    ap.add_argument(
        "--strict-soft",
        action="store_true",
        help="si capas 2–3 emitieron warn → exit 2 (capa 1 fail sigue siendo 1)",
    )
    ap.add_argument(
        "--fix-front",
        action="store_true",
        help="si el n del texto front/README esta stale, corre sync_front_n --fix y reintenta capa 1",
    )
    args = ap.parse_args()
    layers = parse_layers(args.layers)
    out_dir = Path(args.out_dir)
    warnings: list[str] = []

    print(f"validate_corpus — layers={sorted(layers)}  data={DATA}")

    try:
        posters = load_posters()
    except HardFail as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 1

    if 1 in layers and args.fix_front:
        n = int(len(posters))
        issues = check_front_n(n)
        if issues:
            print(f"\n--fix-front: {len(issues)} mismatch(es); sync_front_n…")
            rep = sync_front_n(n)
            if rep.get("stale") is not None:
                print(f"  reemplazado {rep['stale']:,} → {n:,} en {len(rep['files'])} archivos")
            left = check_front_n(n)
            if left:
                print("[FAIL] --fix-front no pudo alinear el texto:", file=sys.stderr)
                for i in left:
                    print(f"  - {i}", file=sys.stderr)
                return 1
            ok("texto front actualizado")

    if 1 in layers:
        try:
            layer1(posters)
        except HardFail as e:
            print(f"\n[FAIL] capa 1: {e}", file=sys.stderr)
            return 1

    if 2 in layers:
        layer2(posters, out_dir, warnings)
    if 3 in layers:
        layer3(posters, out_dir, warnings)

    print("\n=== RESUMEN ===")
    if 1 in layers:
        print("capa 1: PASS")
    if warnings:
        print(f"soft warns: {len(warnings)}")
        if args.strict_soft:
            print("strict-soft: exit 2")
            return 2
    else:
        if 2 in layers or 3 in layers:
            print("soft warns: 0")
    print("LISTO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
