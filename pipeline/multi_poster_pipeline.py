#!/usr/bin/env python3
"""Multi-poster pipeline: list TMDB variants → download → CLIP → pick canonical.

For each movie in posters.csv:
  1) discover  GET /movie/{id}/images (posters; en+null by default)
  2) download  up to --max-per-id into data/posters_multi/{id}/
  3) embed     CLIP ViT-B/32 → data/multi_poster_embeddings.npz
  4) select    cluster near-duplicates (cosine), keep 1 per cluster,
               choose canonical for analysis

Usage:
  source ~/.zshrc
  python3 multi_poster_pipeline.py discover --limit 200
  python3 multi_poster_pipeline.py download --max-per-id 5
  python3 multi_poster_pipeline.py embed
  python3 multi_poster_pipeline.py select --sim 0.96
  python3 multi_poster_pipeline.py report

Does not rewrite posters.csv until you pass --apply (copies canonical → posters/{id}.jpg
and updates poster_paths_backfill.csv).
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
MULTI_DIR = DATA / "posters_multi"
CATALOG = DATA / "multi_poster_catalog.csv"
CANONICAL = DATA / "multi_poster_canonical.csv"
CLUSTERS = DATA / "multi_poster_clusters.csv"
EMB = DATA / "multi_poster_embeddings.npz"
EMB_PARTIAL = DATA / "multi_poster_embeddings_partial.npz"
BACKFILL = DATA / "poster_paths_backfill.csv"
IMG_BASE = "https://image.tmdb.org/t/p/w500"
HEADERS = {"User-Agent": "PulpAnalytics-AnatomyOfFear/1.0-multiposter"}


def _session() -> requests.Session:
    return requests.Session()


def _stem(file_path: str) -> str:
    # "/abc.jpg" → "abc"
    return Path(str(file_path).lstrip("/")).stem


def _local_path(pid: int, file_path: str) -> Path:
    return MULTI_DIR / str(pid) / f"{_stem(file_path)}.jpg"


def cmd_discover(args):
    key = args.api_key or os.environ.get("TMDB_API_KEY")
    if not key:
        raise SystemExit("Need TMDB_API_KEY or --api-key")

    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    meta["id"] = meta["id"].astype(int)
    if args.ids:
        want = {int(x) for x in args.ids.split(",") if x.strip()}
        meta = meta[meta.id.isin(want)]
    if args.limit:
        meta = meta.head(args.limit)

    s = _session()
    rows_out = []
    if CATALOG.exists() and not args.fresh:
        rows_out = list(csv.DictReader(CATALOG.open()))

    done_ids = {int(r["id"]) for r in rows_out}
    todo = [r for r in meta.itertuples(index=False) if int(r.id) not in done_ids]
    print(f"discover todo: {len(todo):,} / {len(meta):,}")
    if done_ids:
        print(f"resume: {len(done_ids):,} ids already in catalog")

    langs = args.langs
    t0 = time.time()
    for i, r in enumerate(todo, 1):
        pid = int(r.id)
        try:
            # one call: primary poster_path + images list
            resp = s.get(
                f"https://api.themoviedb.org/3/movie/{pid}",
                params={
                    "api_key": key,
                    "append_to_response": "images",
                    "include_image_language": langs,
                },
                timeout=30,
            )
            data = resp.json() if resp.ok else {}
        except Exception as e:
            print(f"fail {pid}: {e}", flush=True)
            time.sleep(0.2)
            continue

        prim = data.get("poster_path") or ""
        posters = (data.get("images") or {}).get("posters") or []
        # ensure primary is in the list even if language filter dropped it
        if prim and not any((p.get("file_path") or "") == prim for p in posters):
            posters = [{"file_path": prim, "iso_639_1": "", "vote_average": 0,
                        "vote_count": 0, "width": 0, "height": 0}] + list(posters)
        # rank by votes then average
        posters = sorted(
            posters,
            key=lambda p: (
                float(p.get("vote_average") or 0),
                int(p.get("vote_count") or 0),
                int(p.get("height") or 0),
            ),
            reverse=True,
        )
        if args.max_list:
            posters = posters[: args.max_list]

        for p in posters:
            fp = p.get("file_path") or ""
            if not str(fp).startswith("/"):
                continue
            rows_out.append({
                "id": pid,
                "title": r.title,
                "year": int(r.year) if pd.notna(r.year) else "",
                "file_path": fp,
                "iso_639_1": p.get("iso_639_1") or "",
                "vote_average": float(p.get("vote_average") or 0),
                "vote_count": int(p.get("vote_count") or 0),
                "width": int(p.get("width") or 0),
                "height": int(p.get("height") or 0),
                "is_primary": int(fp == prim),
            })

        if i % 50 == 0 or i == len(todo):
            _write_catalog(rows_out)
            rate = i / max(time.time() - t0, 1e-6)
            print(f"  discover {i}/{len(todo)} ({rate:.1f}/s) catalog={len(rows_out):,}", flush=True)
        time.sleep(args.sleep)

    _write_catalog(rows_out)
    df = pd.DataFrame(rows_out)
    if len(df):
        per = df.groupby("id").size()
        print("\n=== DISCOVER SUMMARY ===")
        print(f"movies: {df.id.nunique():,}  poster rows: {len(df):,}")
        print(f"posters/movie: mean={per.mean():.2f} median={per.median():.0f} "
              f"p90={per.quantile(0.9):.0f} max={per.max()}")
        print(f"movies with ≥2 posters: {(per >= 2).sum():,}")
        print(f"movies with ≥5 posters: {(per >= 5).sum():,}")


def _write_catalog(rows):
    fields = [
        "id", "title", "year", "file_path", "iso_639_1",
        "vote_average", "vote_count", "width", "height", "is_primary",
    ]
    with CATALOG.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def cmd_download(args):
    if not CATALOG.exists():
        raise SystemExit(f"missing {CATALOG} — run discover first")
    cat = pd.read_csv(CATALOG)
    cat["id"] = cat["id"].astype(int)

    # keep top max-per-id by vote_average/vote_count
    cat = cat.sort_values(
        ["id", "vote_average", "vote_count", "height"],
        ascending=[True, False, False, False],
    )
    if args.max_per_id:
        cat = cat.groupby("id", group_keys=False).head(args.max_per_id)

    MULTI_DIR.mkdir(parents=True, exist_ok=True)
    todo = []
    for r in cat.itertuples(index=False):
        dest = _local_path(int(r.id), r.file_path)
        if dest.exists() and dest.stat().st_size > 2000:
            continue
        todo.append((int(r.id), r.file_path, dest))
    print(f"download queue: {len(todo):,} (of {len(cat):,} listed)")

    ok = fail = 0
    session = _session()

    def one(item):
        pid, path, dest = item
        dest.parent.mkdir(parents=True, exist_ok=True)
        # reuse primary corpus file if same path
        primary = POSTERS / f"{pid}.jpg"
        try:
            r = session.get(IMG_BASE + path, headers=HEADERS, timeout=40)
            if r.status_code == 200 and len(r.content) > 2000:
                dest.write_bytes(r.content)
                return True
        except Exception:
            pass
        # fallback: copy primary if this is the only hope
        if primary.exists() and primary.stat().st_size > 2000:
            shutil.copy2(primary, dest)
            return True
        return False

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one, t) for t in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            if fut.result():
                ok += 1
            else:
                fail += 1
            if i % 200 == 0 or i == len(futs):
                print(f"  download {i}/{len(futs)} ok={ok} fail={fail}", flush=True)
    print(f"done ok={ok} fail={fail}")


def cmd_embed(args):
    import torch
    from PIL import Image
    import clip_embed as ce

    if not CATALOG.exists():
        raise SystemExit(f"missing {CATALOG}")
    cat = pd.read_csv(CATALOG)
    cat["id"] = cat["id"].astype(int)
    if args.max_per_id:
        cat = cat.sort_values(
            ["id", "vote_average", "vote_count"], ascending=[True, False, False]
        )
        cat = cat.groupby("id", group_keys=False).head(args.max_per_id)

    keys, paths = [], []
    for r in cat.itertuples(index=False):
        dest = _local_path(int(r.id), r.file_path)
        if dest.exists() and dest.stat().st_size > 2000:
            key = f"{int(r.id)}::{r.file_path}"
            keys.append(key)
            paths.append(dest)

    device = "cuda" if __import__("torch").cuda.is_available() else "cpu"
    print("device:", device, "images:", len(paths))
    model, preprocess = ce.load_clip(device)

    ids_done, vecs = [], []
    if EMB_PARTIAL.exists():
        z = np.load(EMB_PARTIAL)
        ids_done, vecs = list(z["keys"]), list(z["vecs"])
        print(f"resume partial: {len(ids_done):,}")
    elif EMB.exists() and not args.fresh:
        z = np.load(EMB)
        ids_done, vecs = list(z["keys"]), list(z["vecs"])
        print(f"seed from {EMB.name}: {len(ids_done):,}")

    done = set(str(x) for x in ids_done)
    todo_idx = [i for i, k in enumerate(keys) if k not in done]
    print(f"pending embed: {len(todo_idx):,}")

    batch_imgs, batch_keys = [], []
    t0 = time.time()
    n0 = len(ids_done)

    def flush():
        nonlocal batch_imgs, batch_keys
        if not batch_imgs:
            return
        with torch.no_grad():
            f = model.encode_image(torch.stack(batch_imgs).to(device))
            f = f / f.norm(dim=-1, keepdim=True)
        vecs.extend(f.cpu().numpy().astype(np.float16))
        ids_done.extend(batch_keys)
        batch_imgs, batch_keys = [], []

    for j, i in enumerate(todo_idx, 1):
        try:
            batch_imgs.append(preprocess(Image.open(paths[i]).convert("RGB")))
            batch_keys.append(keys[i])
        except Exception:
            continue
        if len(batch_imgs) >= 64:
            flush()
            if len(ids_done) % 1280 < 64:
                rate = (len(ids_done) - n0) / max(time.time() - t0, 1e-6)
                print(f"  {len(ids_done):,} ({rate:.0f}/s)", flush=True)
                np.savez_compressed(
                    EMB_PARTIAL, keys=np.array(ids_done), vecs=np.array(vecs)
                )
    flush()
    np.savez_compressed(EMB, keys=np.array(ids_done), vecs=np.array(vecs))
    EMB_PARTIAL.unlink(missing_ok=True)
    print(f"LISTO: {len(ids_done):,} → {EMB}")


def _score_row(r) -> float:
    return float(r.vote_average) * np.log1p(float(r.vote_count)) + 0.01 * float(r.height)


def cmd_select(args):
    if not CATALOG.exists() or not EMB.exists():
        raise SystemExit("need catalog + embeddings (discover/download/embed)")

    cat = pd.read_csv(CATALOG)
    cat["id"] = cat["id"].astype(int)
    if args.max_per_id:
        cat = cat.sort_values(
            ["id", "vote_average", "vote_count"], ascending=[True, False, False]
        )
        cat = cat.groupby("id", group_keys=False).head(args.max_per_id)

    z = np.load(EMB)
    key_to_vec = {str(k): v for k, v in zip(z["keys"], z["vecs"])}

    cluster_rows = []
    canon_rows = []
    sim_thr = float(args.sim)

    for pid, g in cat.groupby("id"):
        items = []
        for r in g.itertuples(index=False):
            key = f"{int(pid)}::{r.file_path}"
            v = key_to_vec.get(key)
            if v is None:
                continue
            items.append((r, np.asarray(v, dtype=np.float32)))
        if not items:
            continue

        # greedy clustering by descending score
        items.sort(key=lambda x: _score_row(x[0]), reverse=True)
        clusters: list[list[int]] = []  # indices into items
        for i, (_, vi) in enumerate(items):
            placed = False
            for c in clusters:
                # compare to cluster representative (first = best score)
                v0 = items[c[0]][1]
                if float(np.dot(vi, v0)) >= sim_thr:
                    c.append(i)
                    placed = True
                    break
            if not placed:
                clusters.append([i])

        # cluster reps = first member (highest score in that cluster)
        reps = [c[0] for c in clusters]
        # canonical: prefer primary if it is a rep, else best score among reps
        primary_reps = [
            i for i in reps if int(getattr(items[i][0], "is_primary", 0) or 0) == 1
        ]
        if primary_reps:
            best_i = primary_reps[0]
        else:
            best_i = max(reps, key=lambda i: _score_row(items[i][0]))

        best = items[best_i][0]
        n_disc = sum(len(c) - 1 for c in clusters)
        changed = int(int(getattr(best, "is_primary", 0) or 0) == 0)

        for ci, c in enumerate(clusters):
            for j, ii in enumerate(c):
                r = items[ii][0]
                cluster_rows.append({
                    "id": int(pid),
                    "cluster": ci,
                    "file_path": r.file_path,
                    "is_rep": int(j == 0),
                    "is_canonical": int(ii == best_i),
                    "vote_average": r.vote_average,
                    "vote_count": r.vote_count,
                    "iso_639_1": r.iso_639_1,
                })

        canon_rows.append({
            "id": int(pid),
            "title": best.title,
            "year": best.year,
            "canonical_path": best.file_path,
            "n_posters": len(items),
            "n_clusters": len(clusters),
            "n_discarded_variants": n_disc,
            "changed_from_primary": changed,
            "iso_639_1": best.iso_639_1,
            "vote_average": best.vote_average,
            "vote_count": best.vote_count,
        })

    pd.DataFrame(cluster_rows).to_csv(CLUSTERS, index=False)
    pdf = pd.DataFrame(canon_rows)
    pdf.to_csv(CANONICAL, index=False)
    print(f"wrote {CLUSTERS.name} ({len(cluster_rows):,})")
    print(f"wrote {CANONICAL.name} ({len(pdf):,})")
    if len(pdf):
        print(f"mean posters/movie: {pdf.n_posters.mean():.2f}")
        print(f"mean clusters/movie: {pdf.n_clusters.mean():.2f}")
        print(f"total discarded variants: {int(pdf.n_discarded_variants.sum()):,}")
        print(f"canonical ≠ current primary: {int(pdf.changed_from_primary.sum()):,}")

    if args.apply:
        _apply_canonical(pdf)


def _apply_canonical(pdf: pd.DataFrame):
    """Copy canonical multi poster into posters/{id}.jpg and update backfill paths."""
    n = 0
    bf = {}
    if BACKFILL.exists():
        for r in csv.DictReader(BACKFILL.open()):
            try:
                bf[int(r["id"])] = r
            except Exception:
                pass

    for r in pdf.itertuples(index=False):
        pid = int(r.id)
        src = _local_path(pid, r.canonical_path)
        if not src.exists():
            continue
        dest = POSTERS / f"{pid}.jpg"
        shutil.copy2(src, dest)
        bf[pid] = {
            "id": pid,
            "poster_path": r.canonical_path,
            "title": r.title,
            "year": r.year,
        }
        n += 1

    fields = ["id", "poster_path", "title", "year"]
    with BACKFILL.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for pid in sorted(bf):
            w.writerow({k: bf[pid].get(k, "") for k in fields})
    print(f"--apply: copied {n:,} canonical posters → {POSTERS}/ + updated backfill")


def cmd_report(args):
    if not CANONICAL.exists():
        raise SystemExit(f"missing {CANONICAL}")
    pdf = pd.read_csv(CANONICAL)
    print("=== MULTI-POSTER REPORT ===")
    print(f"movies: {len(pdf):,}")
    print(f"posters considered (sum): {int(pdf.n_posters.sum()):,}")
    print(f"clusters (sum): {int(pdf.n_clusters.sum()):,}")
    print(f"discarded near-dup variants: {int(pdf.n_discarded_variants.sum()):,}")
    print(f"kept diverse alts (clusters-1 sum): "
          f"{int((pdf.n_clusters - 1).clip(lower=0).sum()):,}")
    print(f"canonical changed from primary: {int(pdf.changed_from_primary.sum()):,}")
    print("\nposters/movie distribution:")
    print(pdf.n_posters.describe().to_string())
    if CLUSTERS.exists():
        c = pd.read_csv(CLUSTERS)
        print(f"\ncluster file rows: {len(c):,}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="TMDB /images catalog")
    d.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    d.add_argument("--limit", type=int, default=0)
    d.add_argument("--ids", default="")
    d.add_argument("--langs", default="en,null", help="include_image_language")
    d.add_argument("--max-list", type=int, default=20, help="cap posters listed per movie")
    d.add_argument("--sleep", type=float, default=0.035)
    d.add_argument("--fresh", action="store_true")
    d.set_defaults(func=cmd_discover)

    dl = sub.add_parser("download", help="download listed posters")
    dl.add_argument("--max-per-id", type=int, default=5)
    dl.add_argument("--workers", type=int, default=20)
    dl.set_defaults(func=cmd_download)

    e = sub.add_parser("embed", help="CLIP-embed downloaded multi posters")
    e.add_argument("--max-per-id", type=int, default=5)
    e.add_argument("--fresh", action="store_true")
    e.set_defaults(func=cmd_embed)

    s = sub.add_parser("select", help="cluster variants + pick canonical")
    s.add_argument("--sim", type=float, default=0.96, help="cosine threshold for same variant")
    s.add_argument("--max-per-id", type=int, default=5)
    s.add_argument("--apply", action="store_true",
                   help="copy canonical into data/posters/{id}.jpg")
    s.set_defaults(func=cmd_select)

    r = sub.add_parser("report", help="print selection stats")
    r.set_defaults(func=cmd_report)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
