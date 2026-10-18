#!/usr/bin/env python3
# ruff: noqa: B023  # emit() runs inside the same loop iteration that defines it
"""Full-site type-mix (n_type_styles) via CLIP line-crop clustering.

Extends type_mix_pilot.py for full ids-file / all posters with LINE boxes.
Primary columns: id, n_lines, n_type_styles, largest_cluster_share,
mono_or_mixed (derived), year, decade.

  python3 type_mix_score.py \\
    --text-boxes data/qa/type_mix/text_boxes_for_typemix.csv \\
                 /data/out/rekognition_text_boxes_site_full.csv \\
    --ids-file data/qa/type_mix/ids_with_line_boxes.txt \\
    --all-with-lines \\
    --meta data/posters.csv \\
    --posters-dir /data/posters \\
    --out /data/out/type_mix/type_mix_site.csv \\
    --by-decade /data/out/type_mix/type_mix_by_decade.csv
"""

from __future__ import annotations

import argparse
import csv
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import type_mix_pilot as tm

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

OUT_COLS = [
    "id",
    "n_lines",
    "n_type_styles",
    "n_clusters",
    "largest_cluster_share",
    "mono_or_mixed",
    "year",
    "decade",
    "method",
    "notes",
]


def load_meta(path: Path | None) -> dict[int, dict]:
    if path is None or not path.is_file():
        return {}
    out: dict[int, dict] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                pid = int(row["id"])
            except Exception:
                continue
            year = row.get("year") or row.get("Year") or ""
            try:
                y = int(float(year)) if str(year).strip() not in ("", "nan", "None") else None
            except Exception:
                y = None
            decade = f"{(y // 10) * 10}s" if y and 1800 <= y <= 2100 else ""
            out[pid] = {"year": y if y else "", "decade": decade}
    return out


def write_by_decade(out_csv: Path, by_decade_path: Path) -> None:
    buckets: dict[str, list[dict]] = defaultdict(list)
    with out_csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            buckets[row.get("decade") or "unknown"].append(row)
    fields = [
        "decade",
        "n",
        "mean_n_type_styles",
        "median_n_type_styles",
        "mean_n_lines",
        "pct_mixed",
        "pct_mono",
        "pct_unknown",
    ]
    by_decade_path.parent.mkdir(parents=True, exist_ok=True)
    with by_decade_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for decade in sorted(buckets, key=lambda d: (d == "unknown", d)):
            rows = buckets[decade]
            styles, lines = [], []
            lab = Counter()
            for r in rows:
                lab[r.get("mono_or_mixed") or ""] += 1
                try:
                    s = int(float(r.get("n_type_styles") or 0))
                    if s > 0:
                        styles.append(s)
                except Exception:
                    pass
                try:
                    lines.append(int(float(r.get("n_lines") or 0)))
                except Exception:
                    pass
            n = len(rows)
            arr = np.asarray(styles, dtype=float) if styles else np.asarray([0.0])
            w.writerow(
                {
                    "decade": decade,
                    "n": n,
                    "mean_n_type_styles": f"{arr.mean():.3f}" if styles else "",
                    "median_n_type_styles": f"{float(np.median(arr)):.1f}" if styles else "",
                    "mean_n_lines": f"{(sum(lines) / len(lines)):.1f}" if lines else "",
                    "pct_mixed": f"{100 * lab['mixed'] / n:.1f}" if n else "",
                    "pct_mono": f"{100 * lab['mono'] / n:.1f}" if n else "",
                    "pct_unknown": f"{100 * lab['unknown'] / n:.1f}" if n else "",
                }
            )
    print(f"wrote {by_decade_path}", flush=True)


def append_row(out_csv: Path, row: dict, write_header: bool) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow(row)


def main() -> None:
    import torch

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--text-boxes", nargs="+", required=True)
    ap.add_argument("--title-fallback", default="")
    ap.add_argument("--posters-dir", default=str(DATA / "posters"))
    ap.add_argument(
        "--ids-file", default="", help="explicit ids; with --all-with-lines uses text-box ids"
    )
    ap.add_argument(
        "--all-with-lines",
        action="store_true",
        help="process all ids that have ≥1 LINE box (ignores --sample)",
    )
    ap.add_argument("--sample", type=int, default=0, help="0 = all selected ids")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-lines", type=int, default=1)
    ap.add_argument("--distance-threshold", type=float, default=tm.DEFAULT_DISTANCE_THRESHOLD)
    ap.add_argument("--pad", type=float, default=tm.DEFAULT_PAD)
    ap.add_argument("--min-conf", type=float, default=0.0)
    ap.add_argument("--min-box-area", type=float, default=0.0002)
    ap.add_argument("--meta", default="", help="CSV with id,year for decade columns")
    ap.add_argument("--out", required=True)
    ap.add_argument("--by-decade", default="", help="optional decade aggregate CSV")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--progress-every", type=int, default=50)
    ap.add_argument("--device", default="")
    ap.add_argument(
        "--reload-boxes-every",
        type=int,
        default=0,
        help="if >0, reload text-boxes CSVs every N posters (resume as A fills)",
    )
    args = ap.parse_args()

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device={device} threshold={args.distance_threshold}", flush=True)

    box_paths = [Path(p) for p in args.text_boxes]
    boxes = tm.load_text_boxes(box_paths)
    print(
        f"text-boxes ids={len(boxes):,} with_lines={sum(1 for v in boxes.values() if v):,}",
        flush=True,
    )

    meta = load_meta(Path(args.meta) if args.meta else None)
    posters_dir = Path(args.posters_dir)
    out = Path(args.out)
    done = set() if args.force else tm.load_done(out)
    write_header = not out.exists() or out.stat().st_size == 0
    if done:
        print(f"resume: {len(done):,} already in {out}", flush=True)

    if args.ids_file:
        want = [
            int(x)
            for x in Path(args.ids_file).read_text().split()
            if x.strip().lstrip("-").isdigit()
        ]
    elif args.all_with_lines:
        want = sorted(pid for pid, lines in boxes.items() if len(lines) >= args.min_lines)
    else:
        raise SystemExit("need --ids-file or --all-with-lines")

    if args.sample and args.sample > 0 and not args.all_with_lines and not args.ids_file:
        want = want[: args.sample]

    want = [pid for pid in want if pid not in done]
    # Prefer ids that currently have boxes
    with_b = [pid for pid in want if len(boxes.get(pid) or []) >= args.min_lines]
    without = [pid for pid in want if pid not in set(with_b)]
    want = with_b + without
    print(f"todo: {len(want):,} (with_boxes_now={len(with_b)})", flush=True)

    model, preprocess = tm.load_clip(device)
    print("CLIP ViT-B-32 loaded", flush=True)

    t0 = time.time()
    n_ok = 0
    for i, pid in enumerate(want, 1):
        if args.reload_boxes_every and i > 1 and (i - 1) % args.reload_boxes_every == 0:
            boxes = tm.load_text_boxes(box_paths)
            print(f"reloaded text-boxes ids={len(boxes):,}", flush=True)

        notes: list[str] = []
        lines = list(boxes.get(pid) or [])
        kept = []
        for ln in lines:
            box = ln.get("box") or []
            if len(box) < 4:
                continue
            area = float(box[2]) * float(box[3])
            if area < args.min_box_area:
                notes.append("dropped_tiny_box")
                continue
            conf = float(ln.get("conf") or 0)
            if conf and conf < args.min_conf:
                continue
            kept.append(ln)
        lines = kept
        m = meta.get(pid, {})

        def emit(
            n_lines: int, n_type_styles: int, largest, note: str, label: str | None = None
        ) -> None:
            nonlocal write_header
            notes_local = list(dict.fromkeys(notes))
            if note:
                notes_local.append(note)
            if label is None:
                label = tm.decide_label(n_lines, n_type_styles, notes_local)
            row = {
                "id": pid,
                "n_lines": n_lines,
                "n_type_styles": n_type_styles,
                "n_clusters": n_type_styles,
                "largest_cluster_share": largest,
                "mono_or_mixed": label,
                "year": m.get("year", ""),
                "decade": m.get("decade", ""),
                "method": tm.METHOD,
                "notes": ";".join(dict.fromkeys(notes_local)),
            }
            append_row(out, row, write_header)
            write_header = False

        if not lines:
            # skip for now if A may still fill — only emit unknown if not reloading
            if args.reload_boxes_every:
                continue
            emit(0, 0, "", "no_lines")
            continue

        poster = tm.find_poster(posters_dir, pid)
        if poster is None:
            emit(len(lines), 0, "", "missing_poster", "unknown")
            continue

        try:
            from PIL import Image

            img = Image.open(poster).convert("RGB")
            crops = [tm.crop_line(img, ln["box"], pad=args.pad) for ln in lines]
        except Exception as e:
            emit(len(lines), 0, "", f"crop_error:{e}", "unknown")
            continue

        if not crops:
            emit(0, 0, "", "no_lines")
            continue

        try:
            emb = tm.embed_crops(model, preprocess, crops, device)
            n_type_styles, largest_share = tm.cluster_embeddings(emb, args.distance_threshold)
        except Exception as e:
            emit(len(crops), 0, "", f"embed_cluster_error:{e}", "unknown")
            continue

        label = tm.decide_label(len(crops), n_type_styles, notes)
        emit(len(crops), n_type_styles, round(largest_share, 4), "", label)
        n_ok += 1

        if i % args.progress_every == 0 or i == len(want):
            rate = n_ok / max(1e-6, time.time() - t0)
            eta_m = (len(want) - i) / max(rate, 1e-6) / 60
            print(
                f"[{i}/{len(want)}] ok={n_ok} rate={rate:.2f}/s eta={eta_m:.1f}m "
                f"last={pid} styles={n_type_styles} lines={len(crops)} {label}",
                flush=True,
            )

    if args.by_decade and out.is_file():
        write_by_decade(out, Path(args.by_decade))

    if out.is_file():
        labels = Counter()
        styles = []
        with out.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                labels[row.get("mono_or_mixed") or ""] += 1
                try:
                    styles.append(int(float(row.get("n_type_styles") or 0)))
                except Exception:
                    pass
        usable = [s for s in styles if s > 0]
        print("--- summary ---", flush=True)
        print(f"rows={sum(labels.values())}", flush=True)
        if usable:
            arr = np.asarray(usable, dtype=float)
            print(
                f"mean_n_type_styles={arr.mean():.3f} median={np.median(arr):.1f} "
                f"max={int(arr.max())}",
                flush=True,
            )
        for k in ("mono", "mixed", "unknown"):
            tot = sum(labels.values()) or 1
            print(f"  {k}: {labels[k]} ({100 * labels[k] / tot:.1f}%)", flush=True)
        print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
