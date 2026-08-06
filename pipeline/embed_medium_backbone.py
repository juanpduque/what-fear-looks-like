#!/usr/bin/env python3
"""Resumable poster embedding for medium backbone compare (memory-safe).

Designed for ~8GB Macs: CPU, batch_size=1, checkpoint every N images.

  MEDIUM_DEVICE=cpu python3 embed_medium_backbone.py --backbone vitl
  MEDIUM_DEVICE=cpu python3 embed_medium_backbone.py --backbone siglip-base
  MEDIUM_DEVICE=cpu python3 embed_medium_backbone.py --backbone dinov2-base
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
SPLIT = DATA / "qa" / "medium_custom_labels" / "split.csv"
CACHE_DIR = DATA / "qa" / "medium_siglip"


def log(msg: str) -> None:
    print(msg, flush=True)


def pick_device() -> str:
    import torch

    forced = (os.environ.get("MEDIUM_DEVICE") or "").strip().lower()
    if forced in ("cpu", "mps", "cuda"):
        return forced
    return "cpu"


def load_ids() -> list[int]:
    ids: list[int] = []
    with SPLIT.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                ids.append(int(r["id"]))
            except Exception:
                pass
    return sorted(set(ids))


def load_cache(path: Path) -> dict[int, np.ndarray]:
    if not path.exists():
        return {}
    z = np.load(path, allow_pickle=True)
    return {
        int(i): v.astype(np.float32)
        for i, v in zip(np.asarray(z["ids"]), np.asarray(z["vecs"]))
    }


def save_cache(path: Path, by: dict[int, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = np.asarray(sorted(by), dtype=np.int64)
    vecs = np.stack([by[int(i)] for i in ids]).astype(np.float32)
    # Write to a sibling file then atomic replace. Avoid Path.with_suffix tricks:
    # np.savez_compressed("x.npz.writing") may create "x.npz.writing.npz".
    stem = path.name  # e.g. openclip_vitl14_openai.npz
    tmp = path.with_name(stem + ".writing.npz")
    if tmp.exists():
        tmp.unlink()
    np.savez_compressed(tmp, ids=ids, vecs=vecs)
    tmp.replace(path)


def embed_vitl(ids: list[int], cache: Path, save_every: int) -> None:
    import open_clip
    import torch

    by = load_cache(cache)
    todo = [i for i in ids if i not in by]
    log(f"vitl cache={len(by)} todo={len(todo)} device={pick_device()}")
    if not todo:
        return

    ckpt = Path.home() / ".cache" / "clip" / "ViT-L-14.pt"
    if not ckpt.exists():
        raise SystemExit(f"missing {ckpt}")
    device = pick_device()
    prev = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-L-14", pretrained=str(ckpt)
        )
    finally:
        if prev is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = prev
    model = model.to(device).eval()
    for p in model.parameters():
        p.requires_grad_(False)

    t0 = time.time()
    done = 0
    with torch.inference_mode():
        for pid in todo:
            path = POSTERS / f"{pid}.jpg"
            try:
                x = preprocess(Image.open(path).convert("RGB")).unsqueeze(0).to(device)
                f = model.encode_image(x)
                f = f / f.norm(dim=-1, keepdim=True)
                by[pid] = f.float().cpu().numpy()[0].astype(np.float32)
            except Exception as e:
                log(f"fail {pid}: {type(e).__name__}: {e}")
                continue
            done += 1
            if done % 10 == 0 or done == len(todo):
                log(f"vitl {done}/{len(todo)} total={len(by)} elapsed={time.time()-t0:.1f}s")
            if done % save_every == 0:
                save_cache(cache, by)
                log(f"checkpoint {cache} n={len(by)}")
    save_cache(cache, by)
    log(f"done vitl n={len(by)}")


def _siglip_pooled_feats(model, pixel_values):
    """Return L2-normalized SigLIP image embedding Tensor [B, D].

    In transformers>=5, SiglipModel.get_image_features is @can_return_tuple and
    returns BaseModelOutputWithPooling (same as vision_model), not a raw Tensor.
    Calling .norm on that ModelOutput is the AttributeError seen in logs.
    Prefer vision_model + pooler_output via mapping/index (hasattr is unreliable
    on None-stripped ModelOutput fields).
    """
    import torch

    if hasattr(model, "vision_model"):
        raw = model.vision_model(pixel_values=pixel_values)
    elif hasattr(model, "get_image_features"):
        raw = model.get_image_features(pixel_values=pixel_values)
    else:
        raw = model(pixel_values=pixel_values)

    if torch.is_tensor(raw):
        out = raw
    elif isinstance(raw, (tuple, list)):
        # (last_hidden_state, pooler_output, ...)
        po = raw[1] if len(raw) > 1 else None
        lhs = raw[0] if len(raw) > 0 else None
        if po is not None and torch.is_tensor(po):
            out = po
        elif lhs is not None and torch.is_tensor(lhs):
            out = lhs.mean(dim=1)
        else:
            raise TypeError(f"cannot extract siglip features from tuple {type(raw)}")
    else:
        po = None
        lhs = None
        try:
            po = raw["pooler_output"] if "pooler_output" in raw else None
        except Exception:
            po = getattr(raw, "pooler_output", None)
        if po is None:
            try:
                lhs = raw["last_hidden_state"] if "last_hidden_state" in raw else None
            except Exception:
                lhs = getattr(raw, "last_hidden_state", None)
        if po is not None and torch.is_tensor(po):
            out = po
        elif lhs is not None and torch.is_tensor(lhs):
            # SigLIP uses attention pooling; mean is safer than assuming a CLS token.
            out = lhs.mean(dim=1)
        else:
            raise TypeError(f"cannot extract siglip image features from {type(raw)}")

    if not torch.is_tensor(out):
        raise TypeError(f"SigLIP features not a Tensor: {type(out)}")
    return out / out.norm(dim=-1, keepdim=True)


def embed_hf_vision(
    ids: list[int],
    cache: Path,
    model_id: str,
    kind: str,
    save_every: int,
) -> None:
    import torch
    from transformers import AutoImageProcessor, AutoModel, AutoProcessor

    by = load_cache(cache)
    todo = [i for i in ids if i not in by]
    device = pick_device()
    log(f"{kind} model={model_id} cache={len(by)} todo={len(todo)} device={device}")
    if not todo:
        return

    if kind.startswith("siglip"):
        processor = AutoProcessor.from_pretrained(model_id)
        model = AutoModel.from_pretrained(model_id).to(device).eval()

        def encode(imgs):
            inputs = processor(images=imgs, return_tensors="pt")
            pv = inputs["pixel_values"].to(device)
            out = _siglip_pooled_feats(model, pv)
            return out.float().cpu().numpy()

    else:  # dinov2
        processor = AutoImageProcessor.from_pretrained(model_id)
        model = AutoModel.from_pretrained(model_id).to(device).eval()

        def encode(imgs):
            inputs = processor(images=imgs, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            out = model(**inputs).last_hidden_state[:, 0]
            out = out / out.norm(dim=-1, keepdim=True)
            return out.float().cpu().numpy()

    for p in model.parameters():
        p.requires_grad_(False)

    t0 = time.time()
    done = 0
    n_fail = 0
    with torch.inference_mode():
        for pid in todo:
            path = POSTERS / f"{pid}.jpg"
            try:
                img = Image.open(path).convert("RGB")
                by[pid] = encode([img])[0].astype(np.float32)
            except Exception as e:
                n_fail += 1
                log(f"fail {pid}: {type(e).__name__}: {e}")
                continue
            done += 1
            if done % 10 == 0 or done == len(todo):
                log(f"{kind} {done}/{len(todo)} total={len(by)} elapsed={time.time()-t0:.1f}s")
            if done % save_every == 0:
                save_cache(cache, by)
                log(f"checkpoint {cache} n={len(by)}")
    save_cache(cache, by)
    log(f"done {kind} n={len(by)} fail={n_fail}")
    if done == 0 and todo:
        raise SystemExit(f"{kind}: embedded 0/{len(todo)} images (all failed)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--backbone",
        required=True,
        choices=["vitl", "siglip-base", "siglip-so400m", "dinov2-base", "dinov2-large"],
    )
    ap.add_argument("--save-every", type=int, default=10)
    args = ap.parse_args()
    ids = load_ids()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if args.backbone == "vitl":
        embed_vitl(ids, CACHE_DIR / "openclip_vitl14_openai.npz", args.save_every)
    elif args.backbone == "siglip-base":
        embed_hf_vision(
            ids,
            CACHE_DIR / "siglip_base.npz",
            "google/siglip-base-patch16-224",
            "siglip-base",
            args.save_every,
        )
    elif args.backbone == "siglip-so400m":
        embed_hf_vision(
            ids,
            CACHE_DIR / "siglip_so400m14.npz",
            "google/siglip-so400m-patch14-384",
            "siglip-so400m",
            args.save_every,
        )
    elif args.backbone == "dinov2-base":
        embed_hf_vision(
            ids,
            CACHE_DIR / "dinov2_base.npz",
            "facebook/dinov2-base",
            "dinov2-base",
            args.save_every,
        )
    elif args.backbone == "dinov2-large":
        embed_hf_vision(
            ids,
            CACHE_DIR / "dinov2_large.npz",
            "facebook/dinov2-large",
            "dinov2-large",
            args.save_every,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
