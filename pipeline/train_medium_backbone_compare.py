#!/usr/bin/env python3
"""Compare vision backbones for painted/photo/composite medium classification.

Same gold + stratified split as data/qa/medium_custom_labels/ (seed=42, test=0.25).
Linear probe recipe matches baseline: StandardScaler + balanced multinomial LogReg C=2.

Backbones (in order):
  1) CLIP ViT-B/32 from existing clip_embeddings.npz (baseline, apples-to-apples)
  2) OpenCLIP ViT-L-14 (laion2b)
  3) SigLIP SO400M-14
  4) DINOv2-base / DINOv2-large if (2)/(3) do not beat baseline by --delta (default 0.03)

Writes:
  data/qa/medium_backbone_compare/compare_f1.json
  data/qa/medium_backbone_compare/run.log  (also tee via nohup)
  data/qa/medium_siglip/*.npz etc. embedding caches

Does NOT overwrite medium_pred.csv.

  python3 train_medium_backbone_compare.py
  python3 train_medium_backbone_compare.py --skip-dino
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
GOLD_MERGED = DATA / "qa" / "medium_custom_labels" / "gold_merged.csv"
SPLIT_CSV = DATA / "qa" / "medium_custom_labels" / "split.csv"
GOLD_OLD = DATA / "label_qa_medium_train.csv"
GOLD_R3 = DATA / "qa" / "medium_qa_r3_labels.json"
CLIP_EMB = DATA / "clip_embeddings.npz"
OUT = DATA / "qa" / "medium_backbone_compare"
CLASSES = ["painted", "photo", "composite"]


def log(msg: str) -> None:
    print(msg, flush=True)


def load_gold_merged() -> dict[int, str]:
    out: dict[int, str] = {}
    if GOLD_MERGED.exists():
        with GOLD_MERGED.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                lab = (r.get("final_label") or r.get("label") or "").strip().lower()
                if lab not in CLASSES:
                    continue
                try:
                    out[int(r["id"])] = lab
                except Exception:
                    continue
        return out
    # Fallback: merge train + r3 like aws_custom_labels_medium
    if GOLD_OLD.exists():
        with GOLD_OLD.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                lab = (r.get("final_label") or "").strip().lower()
                if lab not in CLASSES:
                    continue
                try:
                    out[int(r["id"])] = lab
                except Exception:
                    pass
    if GOLD_R3.exists():
        d = json.loads(GOLD_R3.read_text(encoding="utf-8"))
        for kid, v in (d.get("verdicts") or {}).items():
            lab = (v.get("label") if isinstance(v, dict) else v) or ""
            lab = str(lab).strip().lower()
            if lab not in CLASSES:
                continue
            try:
                out[int(kid)] = lab
            except Exception:
                pass
    return out


def load_split(gold: dict[int, str]) -> tuple[list[int], list[int]]:
    if not SPLIT_CSV.exists():
        raise FileNotFoundError(f"Missing split: {SPLIT_CSV}")
    train_ids: list[int] = []
    test_ids: list[int] = []
    with SPLIT_CSV.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except Exception:
                continue
            if pid not in gold:
                continue
            sp = (r.get("split") or "").strip().lower()
            if sp == "train":
                train_ids.append(pid)
            elif sp == "test":
                test_ids.append(pid)
    return train_ids, test_ids


def train_eval_logreg(
    name: str,
    emb: dict[int, np.ndarray],
    gold: dict[int, str],
    train_ids: list[int],
    test_ids: list[int],
    C: float = 2.0,
    seed: int = 42,
) -> dict:
    tr = [i for i in train_ids if i in emb]
    te = [i for i in test_ids if i in emb]
    miss_tr = [i for i in train_ids if i not in emb]
    miss_te = [i for i in test_ids if i not in emb]
    Xtr = np.stack([emb[i] for i in tr]).astype(np.float32)
    ytr = [gold[i] for i in tr]
    Xte = np.stack([emb[i] for i in te]).astype(np.float32)
    yte = [gold[i] for i in te]

    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "lr",
                LogisticRegression(
                    C=C,
                    max_iter=2000,
                    class_weight="balanced",
                    random_state=seed,
                ),
            ),
        ]
    )
    t0 = time.time()
    pipe.fit(Xtr, ytr)
    train_s = time.time() - t0
    y_pred = pipe.predict(Xte)
    report = classification_report(
        yte, y_pred, labels=CLASSES, target_names=CLASSES, output_dict=True, zero_division=0
    )
    cm = confusion_matrix(yte, y_pred, labels=CLASSES).tolist()
    macro = float(f1_score(yte, y_pred, labels=CLASSES, average="macro", zero_division=0))
    metrics = {
        "model": name,
        "n_train": len(tr),
        "n_test": len(te),
        "n_missing_train": len(miss_tr),
        "n_missing_test": len(miss_te),
        "missing_train_ids": miss_tr,
        "missing_test_ids": miss_te,
        "emb_dim": int(Xtr.shape[1]),
        "train_seconds": round(train_s, 3),
        "macro_f1_test": macro,
        "report": report,
        "confusion_matrix": cm,
        "classes": CLASSES,
        "class_counts_train": dict(Counter(ytr)),
        "class_counts_test": dict(Counter(yte)),
        "C": C,
        "seed": seed,
    }
    log(
        f"[{name}] macro_f1={macro:.4f} train={len(tr)} test={len(te)} "
        f"dim={Xtr.shape[1]} miss_tr={len(miss_tr)} miss_te={len(miss_te)}"
    )
    log(
        classification_report(yte, y_pred, labels=CLASSES, target_names=CLASSES, zero_division=0)
    )
    return metrics


def l2_normalize(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.clip(norms, 1e-8, None)
    return vecs / norms


def load_clip_b_embeddings(ids_needed: list[int]) -> dict[int, np.ndarray]:
    z = np.load(CLIP_EMB, allow_pickle=True)
    all_ids = np.asarray(z["ids"], dtype=np.int64)
    vecs = np.asarray(z["vecs"], dtype=np.float32)
    vecs = l2_normalize(vecs)
    by = {int(i): v for i, v in zip(all_ids, vecs)}
    return {i: by[i] for i in ids_needed if i in by}


def pick_device() -> str:
    import os
    import torch

    forced = (os.environ.get("MEDIUM_DEVICE") or "").strip().lower()
    if forced in ("cpu", "mps", "cuda"):
        return forced
    # MPS often OOM-kills large ViT-L batches on consumer Macs; default CPU for reliability.
    if os.environ.get("MEDIUM_ALLOW_MPS", "").strip() in ("1", "true", "yes"):
        if torch.backends.mps.is_available():
            return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def embed_open_clip(
    ids: list[int],
    model_name: str,
    pretrained: str,
    cache_path: Path,
    batch_size: int = 16,
    force: bool = False,
) -> dict[int, np.ndarray]:
    if cache_path.exists() and not force:
        z = np.load(cache_path, allow_pickle=True)
        cached = {
            int(i): v.astype(np.float32)
            for i, v in zip(np.asarray(z["ids"]), np.asarray(z["vecs"]))
        }
        missing = [i for i in ids if i not in cached]
        if not missing:
            log(f"cache hit {cache_path} n={len(cached)}")
            return {i: cached[i] for i in ids}
        log(f"cache partial {cache_path} have={len(cached)} missing={len(missing)}; resume missing")
        ids_work = missing
        out_ids = list(cached.keys())
        out_vecs = [cached[i] for i in out_ids]
    else:
        ids_work = list(ids)
        out_ids = []
        out_vecs = []

    import os
    import open_clip
    import torch

    device = pick_device()
    # Prefer local checkpoint path when available (avoids HF Hub hangs for openai tags).
    pretrained_arg = pretrained
    local_candidates = []
    if pretrained in ("openai", "local"):
        local_candidates.append(Path.home() / ".cache" / "clip" / f"{model_name}.pt")
    if Path(pretrained).expanduser().is_file():
        local_candidates.insert(0, Path(pretrained).expanduser())
    for cand in local_candidates:
        if cand.is_file() and cand.stat().st_size > 1_000_000:
            pretrained_arg = str(cand)
            break

    log(f"loading open_clip {model_name}/{pretrained_arg} on {device}…")
    # When using a local .pt, briefly force offline so open_clip won't hit hf_hub tags.
    prev_offline = os.environ.get("HF_HUB_OFFLINE")
    if Path(pretrained_arg).is_file():
        os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained_arg
        )
    finally:
        if prev_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = prev_offline
    model = model.to(device).eval()
    for p in model.parameters():
        p.requires_grad_(False)

    t0 = time.time()
    with torch.inference_mode():
        for start in range(0, len(ids_work), batch_size):
            batch = ids_work[start : start + batch_size]
            imgs = []
            ok_ids = []
            for pid in batch:
                path = POSTERS / f"{pid}.jpg"
                if not path.exists():
                    log(f"  missing poster {path}")
                    continue
                try:
                    img = Image.open(path).convert("RGB")
                    imgs.append(preprocess(img))
                    ok_ids.append(pid)
                except Exception as e:
                    log(f"  fail open {pid}: {e}")
            if not imgs:
                continue
            x = torch.stack(imgs).to(device)
            try:
                feats = model.encode_image(x)
                feats = feats / feats.norm(dim=-1, keepdim=True)
                feats = feats.float().cpu().numpy()
            except Exception as e:
                log(f"  encode batch fail at {start}: {type(e).__name__}: {e}; retrying one-by-one on cpu")
                # Fallback: per-image on CPU
                model_cpu = model.to("cpu")
                for pid, tens in zip(ok_ids, imgs):
                    try:
                        xi = tens.unsqueeze(0)
                        fi = model_cpu.encode_image(xi)
                        fi = fi / fi.norm(dim=-1, keepdim=True)
                        out_ids.append(pid)
                        out_vecs.append(fi.float().cpu().numpy()[0].astype(np.float32))
                    except Exception as e2:
                        log(f"  fail encode {pid}: {e2}")
                model = model_cpu
                device = "cpu"
                continue
            for pid, v in zip(ok_ids, feats):
                out_ids.append(pid)
                out_vecs.append(v.astype(np.float32))
            if (start // batch_size) % 5 == 0 or start + batch_size >= len(ids_work):
                log(
                    f"  {model_name} {min(start + batch_size, len(ids_work))}/{len(ids_work)} "
                    f"total={len(out_ids)} elapsed={time.time() - t0:.1f}s"
                )
            if len(out_ids) % 20 < max(1, batch_size):
                arr_tmp = np.stack(out_vecs).astype(np.float32)
                ids_tmp = np.asarray(out_ids, dtype=np.int64)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(cache_path, ids=ids_tmp, vecs=arr_tmp)

    arr = np.stack(out_vecs).astype(np.float32)
    ids_a = np.asarray(out_ids, dtype=np.int64)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, ids=ids_a, vecs=arr)
    log(f"wrote {cache_path} n={len(out_ids)} dim={arr.shape[1]} s={time.time() - t0:.1f}")
    by = {int(i): v for i, v in zip(ids_a, arr)}
    return {i: by[i] for i in ids if i in by}


def embed_siglip_hf(
    ids: list[int],
    model_id: str,
    cache_path: Path,
    batch_size: int = 4,
    force: bool = False,
) -> dict[int, np.ndarray]:
    if cache_path.exists() and not force:
        z = np.load(cache_path, allow_pickle=True)
        cached = {
            int(i): v.astype(np.float32)
            for i, v in zip(np.asarray(z["ids"]), np.asarray(z["vecs"]))
        }
        if all(i in cached for i in ids):
            log(f"cache hit {cache_path} n={len(cached)}")
            return {i: cached[i] for i in ids}

    import torch
    from transformers import AutoModel, AutoProcessor

    device = pick_device()
    log(f"loading {model_id} on {device}…")
    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id).to(device).eval()
    for p in model.parameters():
        p.requires_grad_(False)

    out_ids: list[int] = []
    out_vecs: list[np.ndarray] = []
    t0 = time.time()
    with torch.inference_mode():
        for start in range(0, len(ids), batch_size):
            batch = ids[start : start + batch_size]
            imgs, ok_ids = [], []
            for pid in batch:
                path = POSTERS / f"{pid}.jpg"
                if not path.exists():
                    continue
                try:
                    imgs.append(Image.open(path).convert("RGB"))
                    ok_ids.append(pid)
                except Exception as e:
                    log(f"  fail open {pid}: {e}")
            if not imgs:
                continue
            inputs = processor(images=imgs, return_tensors="pt")
            pv = inputs["pixel_values"].to(device)
            # Recent transformers: get_image_features returns BaseModelOutputWithPooling
            # (not a Tensor). Unwrap pooler_output before .norm.
            if hasattr(model, "vision_model"):
                raw = model.vision_model(pixel_values=pv)
            elif hasattr(model, "get_image_features"):
                raw = model.get_image_features(pixel_values=pv)
            else:
                raw = model(pixel_values=pv)
            if isinstance(raw, torch.Tensor):
                out = raw
            elif isinstance(raw, (tuple, list)):
                out = raw[1] if len(raw) > 1 and raw[1] is not None else raw[0].mean(dim=1)
            else:
                out = getattr(raw, "pooler_output", None)
                if out is None:
                    lhs = getattr(raw, "last_hidden_state", None)
                    if lhs is None:
                        raise TypeError(f"unexpected SigLIP vision output: {type(raw)}")
                    out = lhs.mean(dim=1)
            if not isinstance(out, torch.Tensor):
                raise TypeError(f"SigLIP features not a Tensor: {type(out)}")
            feats = out / out.norm(dim=-1, keepdim=True)
            feats = feats.float().cpu().numpy()
            for pid, v in zip(ok_ids, feats):
                out_ids.append(pid)
                out_vecs.append(v.astype(np.float32))
            if (start // batch_size) % 5 == 0 or start + batch_size >= len(ids):
                log(
                    f"  siglip {min(start + batch_size, len(ids))}/{len(ids)} "
                    f"elapsed={time.time() - t0:.1f}s"
                )

    arr = np.stack(out_vecs).astype(np.float32)
    ids_a = np.asarray(out_ids, dtype=np.int64)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, ids=ids_a, vecs=arr)
    log(f"wrote {cache_path} n={len(out_ids)} dim={arr.shape[1]} s={time.time() - t0:.1f}")
    return {int(i): v for i, v in zip(ids_a, arr)}


def embed_dinov2(
    ids: list[int],
    hub_name: str,
    cache_path: Path,
    batch_size: int = 8,
    force: bool = False,
) -> dict[int, np.ndarray]:
    if cache_path.exists() and not force:
        z = np.load(cache_path, allow_pickle=True)
        cached = {
            int(i): v.astype(np.float32)
            for i, v in zip(np.asarray(z["ids"]), np.asarray(z["vecs"]))
        }
        if all(i in cached for i in ids):
            log(f"cache hit {cache_path} n={len(cached)}")
            return {i: cached[i] for i in ids}

    import torch
    from torchvision import transforms

    device = pick_device()
    log(f"loading {hub_name} on {device}…")
    # Prefer transformers to avoid torch.hub network quirks when possible
    try:
        from transformers import AutoImageProcessor, AutoModel

        hf_map = {
            "dinov2_vitb14": "facebook/dinov2-base",
            "dinov2_vitl14": "facebook/dinov2-large",
        }
        hf_id = hf_map.get(hub_name, hub_name)
        processor = AutoImageProcessor.from_pretrained(hf_id)
        model = AutoModel.from_pretrained(hf_id).to(device).eval()
        use_hf = True
        preprocess = None
    except Exception as e:
        log(f"transformers DINOv2 failed ({e}); falling back to torch.hub")
        model = torch.hub.load("facebookresearch/dinov2", hub_name)
        model = model.to(device).eval()
        use_hf = False
        preprocess = transforms.Compose(
            [
                transforms.Resize(256, interpolation=transforms.InterpolationMode.BICUBIC),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
            ]
        )
        processor = None

    for p in model.parameters():
        p.requires_grad_(False)

    out_ids: list[int] = []
    out_vecs: list[np.ndarray] = []
    t0 = time.time()
    with torch.inference_mode():
        for start in range(0, len(ids), batch_size):
            batch = ids[start : start + batch_size]
            if use_hf:
                imgs = []
                ok_ids = []
                for pid in batch:
                    path = POSTERS / f"{pid}.jpg"
                    if not path.exists():
                        continue
                    try:
                        imgs.append(Image.open(path).convert("RGB"))
                        ok_ids.append(pid)
                    except Exception as e:
                        log(f"  fail open {pid}: {e}")
                if not imgs:
                    continue
                inputs = processor(images=imgs, return_tensors="pt")
                inputs = {k: v.to(device) for k, v in inputs.items()}
                out = model(**inputs)
                # CLS token
                feats = out.last_hidden_state[:, 0]
                feats = feats / feats.norm(dim=-1, keepdim=True)
                feats = feats.float().cpu().numpy()
            else:
                tensors = []
                ok_ids = []
                for pid in batch:
                    path = POSTERS / f"{pid}.jpg"
                    if not path.exists():
                        continue
                    try:
                        tensors.append(preprocess(Image.open(path).convert("RGB")))
                        ok_ids.append(pid)
                    except Exception as e:
                        log(f"  fail open {pid}: {e}")
                if not tensors:
                    continue
                x = torch.stack(tensors).to(device)
                feats = model(x)
                feats = feats / feats.norm(dim=-1, keepdim=True)
                feats = feats.float().cpu().numpy()
            for pid, v in zip(ok_ids, feats):
                out_ids.append(pid)
                out_vecs.append(v.astype(np.float32))
            if (start // batch_size) % 5 == 0 or start + batch_size >= len(ids):
                log(
                    f"  {hub_name} {min(start + batch_size, len(ids))}/{len(ids)} "
                    f"elapsed={time.time() - t0:.1f}s"
                )

    arr = np.stack(out_vecs).astype(np.float32)
    ids_a = np.asarray(out_ids, dtype=np.int64)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, ids=ids_a, vecs=arr)
    log(f"wrote {cache_path} n={len(out_ids)} dim={arr.shape[1]} s={time.time() - t0:.1f}")
    return {int(i): v for i, v in zip(ids_a, arr)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--C", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--delta", type=float, default=0.03, help="macro-F1 lift to skip DINOv2")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--force-embed", action="store_true")
    ap.add_argument("--skip-dino", action="store_true")
    ap.add_argument("--skip-siglip", action="store_true")
    ap.add_argument("--skip-vitl", action="store_true")
    ap.add_argument(
        "--from-cache",
        action="store_true",
        help="Only train/eval using existing npz caches under data/qa/medium_siglip/",
    )
    ap.add_argument(
        "--only",
        choices=["baseline", "vitl", "siglip", "dinov2b", "dinov2l"],
        nargs="*",
        default=None,
    )
    args = ap.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = DATA / "qa" / "medium_siglip"

    def load_npz(path: Path) -> dict[int, np.ndarray]:
        z = np.load(path, allow_pickle=True)
        return {
            int(i): v.astype(np.float32)
            for i, v in zip(np.asarray(z["ids"]), np.asarray(z["vecs"]))
        }

    gold = load_gold_merged()
    train_ids, test_ids = load_split(gold)
    all_ids = sorted(set(train_ids) | set(test_ids))
    log(
        f"gold={len(gold)} split train={len(train_ids)} test={len(test_ids)} "
        f"all={len(all_ids)} counts={dict(Counter(gold[i] for i in all_ids))} "
        f"device={pick_device()} from_cache={args.from_cache}"
    )

    results: dict[str, dict] = {}
    only = set(args.only) if args.only else None

    def want(key: str) -> bool:
        return only is None or key in only

    # 1) CLIP-B baseline from existing embeddings
    if want("baseline"):
        log("=== CLIP ViT-B baseline (clip_embeddings.npz) ===")
        emb_b = load_clip_b_embeddings(all_ids)
        results["clip_vitb"] = train_eval_logreg(
            "clip_vitb_logreg", emb_b, gold, train_ids, test_ids, C=args.C, seed=args.seed
        )
        (out_dir / "clip_vitb_metrics.json").write_text(
            json.dumps(results["clip_vitb"], indent=2), encoding="utf-8"
        )

    baseline_f1 = float(results.get("clip_vitb", {}).get("macro_f1_test", 0.0))
    if "clip_vitb" not in results and (out_dir / "clip_vitb_metrics.json").exists():
        baseline_f1 = float(
            json.loads((out_dir / "clip_vitb_metrics.json").read_text()).get("macro_f1_test", 0.0)
        )

    # 2) OpenCLIP ViT-L-14
    if want("vitl") and not args.skip_vitl:
        log("=== OpenCLIP ViT-L-14 / openai ===")
        cache = cache_dir / "openclip_vitl14_openai.npz"
        if args.from_cache:
            if not cache.exists():
                log(f"skip vitl: missing cache {cache}")
            else:
                emb_l = load_npz(cache)
                results["openclip_vitl14"] = train_eval_logreg(
                    "openclip_vitl14_openai_logreg",
                    emb_l,
                    gold,
                    train_ids,
                    test_ids,
                    C=args.C,
                    seed=args.seed,
                )
                (out_dir / "openclip_vitl14_metrics.json").write_text(
                    json.dumps(results["openclip_vitl14"], indent=2), encoding="utf-8"
                )
        else:
            emb_l = embed_open_clip(
                all_ids,
                "ViT-L-14",
                "openai",
                cache,
                batch_size=1,
                force=args.force_embed,
            )
            results["openclip_vitl14"] = train_eval_logreg(
                "openclip_vitl14_openai_logreg",
                emb_l,
                gold,
                train_ids,
                test_ids,
                C=args.C,
                seed=args.seed,
            )
            (out_dir / "openclip_vitl14_metrics.json").write_text(
                json.dumps(results["openclip_vitl14"], indent=2), encoding="utf-8"
            )

    # 3) SigLIP (so400m preferred; base fallback cache)
    if want("siglip") and not args.skip_siglip:
        log("=== SigLIP ===")
        cache_so = cache_dir / "siglip_so400m14.npz"
        cache_base = cache_dir / "siglip_base.npz"
        emb_s = None
        model_key = "siglip_so400m"
        if args.from_cache:
            if cache_so.exists():
                emb_s = load_npz(cache_so)
                model_key = "siglip_so400m"
            elif cache_base.exists():
                emb_s = load_npz(cache_base)
                model_key = "siglip_base"
            else:
                log("skip siglip: no cache")
        else:
            try:
                emb_s = embed_siglip_hf(
                    all_ids,
                    "google/siglip-so400m-patch14-384",
                    cache_so,
                    batch_size=1,
                    force=args.force_embed,
                )
                model_key = "siglip_so400m"
            except Exception as e:
                log(f"SigLIP SO400M failed ({e}); trying base")
                emb_s = embed_siglip_hf(
                    all_ids,
                    "google/siglip-base-patch16-224",
                    cache_base,
                    batch_size=1,
                    force=args.force_embed,
                )
                model_key = "siglip_base"
        if emb_s is not None:
            results[model_key] = train_eval_logreg(
                f"{model_key}_logreg",
                emb_s,
                gold,
                train_ids,
                test_ids,
                C=args.C,
                seed=args.seed,
            )
            (out_dir / f"{model_key}_metrics.json").write_text(
                json.dumps(results[model_key], indent=2), encoding="utf-8"
            )

    best_new = 0.0
    for k in ("openclip_vitl14", "siglip_so400m", "siglip_base"):
        if k in results:
            best_new = max(best_new, float(results[k]["macro_f1_test"]))
    for name, fname in (
        ("openclip_vitl14", "openclip_vitl14_metrics.json"),
        ("siglip_so400m", "siglip_so400m_metrics.json"),
        ("siglip_base", "siglip_base_metrics.json"),
    ):
        if name not in results and (out_dir / fname).exists():
            m = json.loads((out_dir / fname).read_text())
            results[name] = m
            best_new = max(best_new, float(m["macro_f1_test"]))

    need_dino = (best_new < baseline_f1 + args.delta) and not args.skip_dino
    if only is not None:
        need_dino = any(x in only for x in ("dinov2b", "dinov2l"))
    if args.from_cache:
        # Always eval whatever dino caches exist when from-cache.
        need_dino = True

    if need_dino:
        log(
            f"=== DINOv2 (best_new={best_new:.4f} baseline={baseline_f1:.4f}+{args.delta}) ==="
        )
        if want("dinov2b") or only is None or args.from_cache:
            cache = cache_dir / "dinov2_base.npz"
            if args.from_cache:
                if cache.exists():
                    emb_d = load_npz(cache)
                    results["dinov2_base"] = train_eval_logreg(
                        "dinov2_base_logreg",
                        emb_d,
                        gold,
                        train_ids,
                        test_ids,
                        C=args.C,
                        seed=args.seed,
                    )
                    (out_dir / "dinov2_base_metrics.json").write_text(
                        json.dumps(results["dinov2_base"], indent=2), encoding="utf-8"
                    )
                else:
                    log(f"skip dinov2_base: missing {cache}")
            else:
                emb_d = embed_dinov2(
                    all_ids,
                    "dinov2_vitb14",
                    cache,
                    batch_size=1,
                    force=args.force_embed,
                )
                results["dinov2_base"] = train_eval_logreg(
                    "dinov2_base_logreg",
                    emb_d,
                    gold,
                    train_ids,
                    test_ids,
                    C=args.C,
                    seed=args.seed,
                )
                (out_dir / "dinov2_base_metrics.json").write_text(
                    json.dumps(results["dinov2_base"], indent=2), encoding="utf-8"
                )

        base_f1 = float(results.get("dinov2_base", {}).get("macro_f1_test", 0.0))
        try_large = want("dinov2l") or (
            (only is None or args.from_cache) and base_f1 < baseline_f1 + args.delta
        )
        if try_large or (args.from_cache and (cache_dir / "dinov2_large.npz").exists()):
            cache = cache_dir / "dinov2_large.npz"
            if args.from_cache:
                if cache.exists():
                    emb_dl = load_npz(cache)
                    results["dinov2_large"] = train_eval_logreg(
                        "dinov2_large_logreg",
                        emb_dl,
                        gold,
                        train_ids,
                        test_ids,
                        C=args.C,
                        seed=args.seed,
                    )
                    (out_dir / "dinov2_large_metrics.json").write_text(
                        json.dumps(results["dinov2_large"], indent=2), encoding="utf-8"
                    )
            else:
                emb_dl = embed_dinov2(
                    all_ids,
                    "dinov2_vitl14",
                    cache,
                    batch_size=1,
                    force=args.force_embed,
                )
                results["dinov2_large"] = train_eval_logreg(
                    "dinov2_large_logreg",
                    emb_dl,
                    gold,
                    train_ids,
                    test_ids,
                    C=args.C,
                    seed=args.seed,
                )
                (out_dir / "dinov2_large_metrics.json").write_text(
                    json.dumps(results["dinov2_large"], indent=2), encoding="utf-8"
                )
    else:
        log(
            f"skip DINOv2: best_new={best_new:.4f} >= baseline={baseline_f1:.4f}+{args.delta}"
        )

    # Aggregate compare
    # Reload any metrics files for complete compare
    for fname, key in (
        ("clip_vitb_metrics.json", "clip_vitb"),
        ("openclip_vitl14_metrics.json", "openclip_vitl14"),
        ("siglip_so400m_metrics.json", "siglip_so400m"),
        ("siglip_base_metrics.json", "siglip_base"),
        ("dinov2_base_metrics.json", "dinov2_base"),
        ("dinov2_large_metrics.json", "dinov2_large"),
    ):
        p = out_dir / fname
        if key not in results and p.exists():
            results[key] = json.loads(p.read_text(encoding="utf-8"))

    ranked = sorted(
        ((k, float(v["macro_f1_test"])) for k, v in results.items()),
        key=lambda x: -x[1],
    )
    winner_key, winner_f1 = ranked[0] if ranked else ("none", 0.0)
    baseline = float(results.get("clip_vitb", {}).get("macro_f1_test", baseline_f1))
    clear_win = winner_key != "clip_vitb" and winner_f1 >= baseline + args.delta

    compare = {
        "gold_n": len(all_ids),
        "n_train": len(train_ids),
        "n_test": len(test_ids),
        "split_csv": str(SPLIT_CSV),
        "gold_csv": str(GOLD_MERGED if GOLD_MERGED.exists() else "merged_on_fly"),
        "seed": args.seed,
        "C": args.C,
        "delta_threshold": args.delta,
        "device": pick_device(),
        "baseline_macro_f1": baseline,
        "winner": winner_key,
        "winner_macro_f1": winner_f1,
        "clear_win_vs_baseline": clear_win,
        "lift_vs_baseline": round(winner_f1 - baseline, 4),
        "ranked": [{"model": k, "macro_f1_test": f} for k, f in ranked],
        "per_model": {
            k: {
                "macro_f1_test": float(v["macro_f1_test"]),
                "emb_dim": v.get("emb_dim"),
                "n_train": v.get("n_train"),
                "n_test": v.get("n_test"),
                "per_class_f1": {
                    c: float(v["report"][c]["f1-score"]) for c in CLASSES if c in v.get("report", {})
                },
            }
            for k, v in results.items()
        },
        "note_full_corpus": (
            "Do NOT overwrite medium_pred.csv unless clear win. "
            "To re-embed full corpus after a win: reuse embed_open_clip/embed_dinov2 "
            "over all poster ids, then fit LogReg on gold train and predict."
            if clear_win
            else "No clear win (≥+0.03 macro-F1); keep CLIP-B medium_pred.csv."
        ),
    }
    compare_path = out_dir / "compare_f1.json"
    compare_path.write_text(json.dumps(compare, indent=2), encoding="utf-8")
    log(f"wrote {compare_path}")
    log(
        f"WINNER={winner_key} F1={winner_f1:.4f} baseline={baseline:.4f} "
        f"lift={winner_f1 - baseline:+.4f} clear_win={clear_win}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        raise
