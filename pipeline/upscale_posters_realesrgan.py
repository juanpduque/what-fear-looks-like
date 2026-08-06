#!/usr/bin/env python3
"""Upscale posters with Real-ESRGAN via spandrel (no basicsr; works on py3.13).

  python3 upscale_posters_realesrgan.py \\
    --ids-file data/qa/posters_upscale_ids.txt \\
    --in-dir data/posters_original \\
    --out-dir data/posters_original_up \\
    --outscale 2 --tile 400
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.nn import functional as F


def load_ids(path: Path) -> list[int]:
    return [int(x) for x in path.read_text().splitlines() if x.strip()]


def load_model(weights: Path, half: bool):
    from spandrel import ImageModelDescriptor, ModelLoader

    desc = ModelLoader().load_from_file(str(weights))
    if not isinstance(desc, ImageModelDescriptor):
        raise SystemExit(f"unexpected model type: {type(desc)}")
    desc = desc.cuda().eval()
    if half:
        desc = desc.half()
    return desc


def tiled_enhance(
    model,
    img_bgr: np.ndarray,
    *,
    outscale: float,
    tile: int,
    tile_pad: int,
    half: bool,
) -> np.ndarray:
    """img_bgr uint8 HWC → upscaled BGR uint8 (approx outscale)."""
    img = img_bgr.astype(np.float32) / 255.0
    img = img[:, :, ::-1].copy()  # BGR→RGB
    h, w = img.shape[:2]
    # model native scale (x2 weights); then resize if outscale differs
    native = getattr(model, "scale", 2) or 2

    def run_tensor(thw: torch.Tensor) -> torch.Tensor:
        with torch.no_grad():
            if half:
                thw = thw.half()
            return model(thw)

    if tile <= 0 or max(h, w) <= tile:
        t = torch.from_numpy(np.transpose(img, (2, 0, 1))).unsqueeze(0).cuda()
        out = run_tensor(t).float().clamp_(0, 1).squeeze(0).cpu().numpy()
        out = np.transpose(out, (1, 2, 0))
    else:
        # tiled inference with overlap
        out_h, out_w = h * native, w * native
        output = np.zeros((out_h, out_w, 3), dtype=np.float32)
        weights = np.zeros((out_h, out_w, 1), dtype=np.float32)
        stride = tile - tile_pad
        ys = list(range(0, h, stride))
        xs = list(range(0, w, stride))
        if ys[-1] + tile < h:
            ys.append(max(0, h - tile))
        if xs[-1] + tile < w:
            xs.append(max(0, w - tile))
        for y in ys:
            for x in xs:
                y1, x1 = y, x
                y2, x2 = min(y + tile, h), min(x + tile, w)
                y1, x1 = max(0, y2 - tile), max(0, x2 - tile)
                tile_img = img[y1:y2, x1:x2, :]
                t = torch.from_numpy(np.transpose(tile_img, (2, 0, 1))).unsqueeze(0).cuda()
                out_t = run_tensor(t).float().clamp_(0, 1).squeeze(0).cpu().numpy()
                out_t = np.transpose(out_t, (1, 2, 0))
                oy1, ox1 = y1 * native, x1 * native
                oy2, ox2 = y2 * native, x2 * native
                # feather
                th, tw = out_t.shape[:2]
                wy = np.linspace(0.25, 1.0, th // 2, dtype=np.float32)
                if th % 2:
                    mask_y = np.concatenate([wy, wy[::-1], [1.0]])
                else:
                    mask_y = np.concatenate([wy, wy[::-1]])
                wx = np.linspace(0.25, 1.0, tw // 2, dtype=np.float32)
                if tw % 2:
                    mask_x = np.concatenate([wx, wx[::-1], [1.0]])
                else:
                    mask_x = np.concatenate([wx, wx[::-1]])
                mask = np.outer(mask_y[:th], mask_x[:tw])[:, :, None]
                output[oy1:oy2, ox1:ox2, :] += out_t * mask
                weights[oy1:oy2, ox1:ox2, :] += mask
        output = output / np.maximum(weights, 1e-6)
        out = output

    out = (out[:, :, ::-1] * 255.0).round().astype(np.uint8)  # RGB→BGR
    if abs(outscale - native) > 1e-3:
        nh, nw = int(round(h * outscale)), int(round(w * outscale))
        t = torch.from_numpy(out[:, :, ::-1].copy()).permute(2, 0, 1).unsqueeze(0).float() / 255.0
        t = F.interpolate(t, size=(nh, nw), mode="bicubic", align_corners=False)
        out = (t.squeeze(0).permute(1, 2, 0).numpy()[:, :, ::-1] * 255.0).round().astype(np.uint8)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids-file", type=Path, required=True)
    ap.add_argument("--in-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--weights", type=Path, default=Path("weights/RealESRGAN_x2plus.pth"))
    ap.add_argument("--outscale", type=float, default=2.0)
    ap.add_argument("--tile", type=int, default=400)
    ap.add_argument("--min-width", type=int, default=1000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--fp32", action="store_true")
    ap.add_argument("--progress-every", type=int, default=25)
    args = ap.parse_args()

    ids = load_ids(args.ids_file)
    if args.limit:
        ids = ids[: args.limit]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    prog = Path("data/qa/posters_upscale_progress.csv")
    prog.parent.mkdir(parents=True, exist_ok=True)

    if not args.weights.exists():
        sys.exit(f"missing weights: {args.weights}")
    if not torch.cuda.is_available():
        sys.exit("CUDA required")

    half = not args.fp32
    print(
        f"torch={torch.__version__} cuda=True n={len(ids)} outscale={args.outscale} "
        f"tile={args.tile} half={half} gpu={torch.cuda.get_device_name(0)}",
        flush=True,
    )
    model = load_model(args.weights, half=half)

    rows: list[dict] = []
    if prog.exists():
        rows = list(csv.DictReader(prog.open()))
    ok = skip = err = 0
    t0 = time.time()

    for i, pid in enumerate(ids, 1):
        out_path = args.out_dir / f"{pid}.jpg"
        in_path = args.in_dir / f"{pid}.jpg"
        if out_path.exists() and out_path.stat().st_size > 1000:
            skip += 1
            continue
        if not in_path.exists():
            err += 1
            rows.append(
                {
                    "id": pid,
                    "status": "missing_in",
                    "in_w": "",
                    "in_h": "",
                    "out_w": "",
                    "out_h": "",
                    "latency_s": "",
                    "error": "missing input",
                }
            )
            continue
        try:
            with Image.open(in_path) as im0:
                im = im0.convert("RGB")
                w0, h0 = im.size
            if w0 >= args.min_width:
                skip += 1
                continue
            # RGB→BGR for enhance helper
            rgb = np.asarray(im)
            bgr = rgb[:, :, ::-1].copy()
            t1 = time.time()
            out_bgr = tiled_enhance(
                model, bgr, outscale=args.outscale, tile=args.tile, tile_pad=10, half=half
            )
            latency = round(time.time() - t1, 3)
            out_rgb = out_bgr[:, :, ::-1]
            out_im = Image.fromarray(out_rgb)
            tmp = out_path.with_suffix(".partial.jpg")
            out_im.save(tmp, format="JPEG", quality=92, optimize=True)
            tmp.replace(out_path)
            ow, oh = out_im.size
            ok += 1
            rows.append(
                {
                    "id": pid,
                    "status": "ok",
                    "in_w": w0,
                    "in_h": h0,
                    "out_w": ow,
                    "out_h": oh,
                    "latency_s": latency,
                    "error": "",
                }
            )
        except Exception as e:
            err += 1
            rows.append(
                {
                    "id": pid,
                    "status": "error",
                    "in_w": "",
                    "in_h": "",
                    "out_w": "",
                    "out_h": "",
                    "latency_s": "",
                    "error": str(e)[:300],
                }
            )

        if i % args.progress_every == 0 or i == len(ids):
            by_id = {int(r["id"]): r for r in rows}
            with prog.open("w", newline="", encoding="utf-8") as f:
                wri = csv.DictWriter(
                    f,
                    fieldnames=["id", "status", "in_w", "in_h", "out_w", "out_h", "latency_s", "error"],
                )
                wri.writeheader()
                for r in sorted(by_id.values(), key=lambda x: int(x["id"])):
                    wri.writerow(r)
            print(
                f"[{i}/{len(ids)}] ok={ok} skip={skip} err={err} "
                f"elapsed={time.time()-t0:.0f}s last={pid}",
                flush=True,
            )

    print(f"LISTO ok={ok} skip={skip} err={err} → {args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
