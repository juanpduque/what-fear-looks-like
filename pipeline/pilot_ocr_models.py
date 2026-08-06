#!/usr/bin/env python3
"""Pilot: compare OCR / VLM models on a small sample of horror posters.

Models (lazy-loaded; one failure does not abort the rest):
  got        → stepfun-ai/GOT-OCR-2.0-hf
  deepseek   → deepseek-ai/DeepSeek-OCR  (falls back to DeepSeek-OCR-2)
  deepseek2  → deepseek-ai/DeepSeek-OCR-2 only (image_size=768)
  unlimited  → baidu/Unlimited-OCR (DeepSeek-style infer API)
  glm        → zai-org/GLM-OCR (~0.9–1.3B; prompt "Text Recognition:")
  paddle     → PaddlePaddle/PaddleOCR-VL
  qianfan    → baidu/Qianfan-OCR  (~5B — may OOM on 16 GB)
  qwen       → Qwen/Qwen2-VL-2B-Instruct  (or Qwen2.5-VL-3B if set)
  qwen7      → Qwen/Qwen2-VL-7B-Instruct (bf16; falls back to 4bit if OOM)
  kimi       → moonshotai/Kimi-VL-A3B-Instruct (16B MoE / 3B act; 4bit on 24GB)

Device priority: CUDA > MPS > CPU.

Outputs:
  data/qa/ocr_pilot/{model}/{id}.txt
  data/qa/ocr_pilot/results.csv
  data/qa/ocr_pilot/sample_ids.txt

Install (Deep Learning AMI / CUDA):
  pip install -U pip
  pip install -U 'transformers>=4.51' accelerate pillow pandas numpy torch torchvision
  # optional for DeepSeek flash-attn (skip if install fails):
  #   pip install flash-attn --no-build-isolation

Local sample (no inference):
  python3 pilot_ocr_models.py --dry-sample --n 20 --seed 42

Run subset:
  python3 pilot_ocr_models.py --n 20 --models got,qwen --seed 42

Hard12 (GLM + Unlimited + DeepSeek-OCR-2):
  python3 pilot_ocr_models.py --ids-file data/qa/ocr_qwen_hard/sample_ids.txt \\
      --out-dir data/qa/ocr_hard12_new --models glm,unlimited,deepseek2 \\
      --posters-dir data/qa/_ocr_hard12_new_stage/posters
  # AWS: bash aws/stage_ocr_hard12_new.sh && \\
  #       MODELS=glm,unlimited,deepseek2 bash aws/launch_ocr_hard12_new.sh

AWS GPU (see pipeline/aws/launch_ocr_pilot.sh):
  python3 pilot_ocr_models.py --n 20 --ids-file data/qa/ocr_pilot/sample_ids.txt \\
      --models got,deepseek,paddle,qianfan,qwen

VRAM note: g4dn.xlarge = 16 GB. Qianfan (~5B) and DeepSeek may OOM;
those rows get status=error and the pilot continues. Prefer g5.2xlarge
for unlimited / deepseek2 / kimi.
"""
from __future__ import annotations

import argparse
import csv
import gc
import re
import sys
import time
import traceback
from pathlib import Path

import pandas as pd

from ocr_metrics import title_overlap_score

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
POSTERS_CSV = DATA / "posters.csv"
ATTR_CSV = DATA / "attributes.csv"
DEFAULT_OUT_DIR = DATA / "qa" / "ocr_pilot"

# Mutable paths (set via --out-dir / --posters-dir)
OUT_DIR = DEFAULT_OUT_DIR
RESULTS_CSV = OUT_DIR / "results.csv"
SAMPLE_IDS = OUT_DIR / "sample_ids.txt"

RESULT_FIELDS = [
    "id",
    "title",
    "year",
    "model",
    "text",
    "chars",
    "title_overlap_score",
    "latency_s",
    "status",
]


def configure_out_dir(path: str | Path) -> None:
    global OUT_DIR, RESULTS_CSV, SAMPLE_IDS
    OUT_DIR = Path(path)
    RESULTS_CSV = OUT_DIR / "results.csv"
    SAMPLE_IDS = OUT_DIR / "sample_ids.txt"


def configure_posters_dir(path: str | Path) -> None:
    global POSTERS
    POSTERS = Path(path)

MODEL_IDS = {
    "got": "stepfun-ai/GOT-OCR-2.0-hf",
    "deepseek": "deepseek-ai/DeepSeek-OCR",
    "deepseek2": "deepseek-ai/DeepSeek-OCR-2",
    "unlimited": "baidu/Unlimited-OCR",
    "glm": "zai-org/GLM-OCR",
    "paddle": "PaddlePaddle/PaddleOCR-VL",
    "qianfan": "baidu/Qianfan-OCR",
    "qwen": "Qwen/Qwen2-VL-2B-Instruct",
    "qwen7": "Qwen/Qwen2-VL-7B-Instruct",
    "kimi": "moonshotai/Kimi-VL-A3B-Instruct",
}

OCR_PROMPT = (
    "Extract ALL visible text from this movie poster. "
    "Return plain text only, no commentary."
)


def pick_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def unload_cuda() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass


def load_sample(
    n: int,
    seed: int,
    ids_file: str | None,
) -> pd.DataFrame:
    posters = pd.read_csv(POSTERS_CSV, usecols=["id", "title", "year"])
    posters["id"] = posters["id"].astype(int)

    if ids_file:
        raw = Path(ids_file).read_text(encoding="utf-8")
        ids = [int(x) for x in re.split(r"[\s,]+", raw.strip()) if x.strip()]
        df = posters[posters["id"].isin(ids)].copy()
        # preserve order from file
        order = {pid: i for i, pid in enumerate(ids)}
        df["_ord"] = df["id"].map(order)
        return df.sort_values("_ord").drop(columns=["_ord"]).reset_index(drop=True)

    # Mix high / low text_area from attributes
    if ATTR_CSV.exists():
        attr = pd.read_csv(ATTR_CSV, usecols=["id", "text_area"])
        attr["id"] = attr["id"].astype(int)
        m = posters.merge(attr, on="id", how="inner")
    else:
        m = posters.copy()
        m["text_area"] = 0.5

    # only ids with local jpg
    have = []
    for pid in m["id"]:
        if (POSTERS / f"{pid}.jpg").exists():
            have.append(pid)
    m = m[m["id"].isin(have)].copy()
    if m.empty:
        raise SystemExit(f"no local posters under {POSTERS}")

    rng = pd.Series(dtype=int)
    half = max(1, n // 2)
    hi = m.nlargest(max(half * 4, n), "text_area")
    lo = m.nsmallest(max(half * 4, n), "text_area")
    hi_s = hi.sample(n=min(half, len(hi)), random_state=seed)
    lo_s = lo.sample(n=min(n - len(hi_s), len(lo)), random_state=seed + 1)
    # fill remainder from middle if needed
    picked = pd.concat([hi_s, lo_s]).drop_duplicates("id")
    if len(picked) < n:
        rest = m[~m["id"].isin(picked["id"])].sample(
            n=min(n - len(picked), len(m) - len(picked)),
            random_state=seed + 2,
        )
        picked = pd.concat([picked, rest])
    return picked.head(n).reset_index(drop=True)


def write_results(rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def append_result(rows: list[dict], row: dict) -> None:
    rows.append(row)
    write_results(rows)
    model_dir = OUT_DIR / row["model"]
    model_dir.mkdir(parents=True, exist_ok=True)
    if row.get("status") == "ok" and row.get("text"):
        (model_dir / f"{row['id']}.txt").write_text(row["text"], encoding="utf-8")


# ── model runners ────────────────────────────────────────────────────────────


class GotRunner:
    name = "got"
    hf_id = MODEL_IDS["got"]

    def __init__(self, device: str):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.device = device
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        kwargs = {"torch_dtype": dtype}
        if device == "cuda":
            kwargs["device_map"] = "auto"
        self.model = AutoModelForImageTextToText.from_pretrained(self.hf_id, **kwargs)
        if device != "cuda":
            self.model = self.model.to(device)
        self.model.eval()
        self.processor = AutoProcessor.from_pretrained(self.hf_id, use_fast=True)

    def run(self, image_path: Path) -> str:
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        inputs = self.processor(image, return_tensors="pt")
        inputs = {k: v.to(self.device) if hasattr(v, "to") else v for k, v in inputs.items()}
        gen = self.model.generate(
            **inputs,
            do_sample=False,
            tokenizer=self.processor.tokenizer,
            stop_strings="<|im_end|>",
            max_new_tokens=1024,
        )
        in_len = inputs["input_ids"].shape[1]
        return self.processor.decode(gen[0, in_len:], skip_special_tokens=True).strip()

    def close(self) -> None:
        del self.model, self.processor
        unload_cuda()


class DeepseekRunner:
    """DeepSeek-OCR family via AutoModel.infer (trust_remote_code).

    Keys:
      deepseek  → try DeepSeek-OCR then DeepSeek-OCR-2 (image_size=640)
      deepseek2 → DeepSeek-OCR-2 only (image_size=768 per model card)
    """

    name = "deepseek"
    # Official ids first; community fork last (patched for newer transformers).
    candidates = (
        "deepseek-ai/DeepSeek-OCR",
        "deepseek-ai/DeepSeek-OCR-2",
        "strangervisionhf/deepseek-ocr-2-transformers-v4.57.1",
    )
    prompt = "<image>\nFree OCR. "
    base_size = 1024
    image_size = 640
    crop_mode = True

    def __init__(
        self,
        device: str,
        name: str | None = None,
        candidates: tuple[str, ...] | None = None,
        image_size: int | None = None,
    ):
        import torch
        from transformers import AutoModel, AutoTokenizer

        if device != "cuda":
            raise RuntimeError("DeepSeek-OCR needs CUDA (trust_remote_code + .cuda())")
        if name:
            self.name = name
        if candidates is not None:
            self.candidates = candidates
        if image_size is not None:
            self.image_size = image_size
        self.device = device
        # Newer transformers removed LlamaFlashAttention2; DeepSeek remote code still imports it.
        self._patch_llama_flash_attn()
        last_err: Exception | None = None
        self.model = None
        self.tokenizer = None
        self.hf_id = self.candidates[0]
        for mid in self.candidates:
            try:
                from transformers import AutoConfig

                tok = AutoTokenizer.from_pretrained(mid, trust_remote_code=True)
                cfg = AutoConfig.from_pretrained(mid, trust_remote_code=True)
                # DeepSeek-OCR-2 configs may omit pad_token_id; newer HF requires it
                pad = getattr(tok, "pad_token_id", None)
                if pad is None:
                    pad = getattr(tok, "eos_token_id", None)
                if pad is None:
                    pad = getattr(cfg, "eos_token_id", None)
                if pad is None:
                    pad = 0
                for obj in (cfg,):
                    try:
                        obj.pad_token_id = pad
                    except Exception:
                        try:
                            object.__setattr__(obj, "pad_token_id", pad)
                        except Exception:
                            obj.__dict__["pad_token_id"] = pad
                # Some remote configs use custom __getattr__; force via dict
                try:
                    cfg.__dict__.setdefault("pad_token_id", pad)
                except Exception:
                    pass
                if getattr(tok, "pad_token_id", None) is None:
                    try:
                        tok.pad_token = tok.eos_token
                        tok.pad_token_id = pad
                    except Exception:
                        pass

                load_kwargs = dict(
                    trust_remote_code=True,
                    use_safetensors=True,
                    torch_dtype=torch.bfloat16,
                    config=cfg,
                )
                try:
                    model = AutoModel.from_pretrained(
                        mid,
                        _attn_implementation="eager",
                        **load_kwargs,
                    )
                except TypeError:
                    model = AutoModel.from_pretrained(mid, **load_kwargs)
                except Exception:
                    # retry without explicit config (some remote code rejects patched cfg)
                    load_kwargs.pop("config", None)
                    try:
                        model = AutoModel.from_pretrained(
                            mid,
                            _attn_implementation="eager",
                            **load_kwargs,
                        )
                    except TypeError:
                        model = AutoModel.from_pretrained(mid, **load_kwargs)
                if getattr(model.config, "pad_token_id", None) is None:
                    try:
                        model.config.pad_token_id = pad
                    except Exception:
                        pass
                model = model.eval().cuda().to(torch.bfloat16)
                self.tokenizer = tok
                self.model = model
                self.hf_id = mid
                # OCR-2 model card uses image_size=768; keep caller override if set
                if image_size is None and "OCR-2" in mid:
                    self.image_size = 768
                print(
                    f"  {self.name} loaded: {mid} image_size={self.image_size}",
                    flush=True,
                )
                break
            except Exception as e:
                last_err = e
                print(f"  {self.name} try failed {mid}: {e}", flush=True)
                unload_cuda()
        if self.model is None:
            raise RuntimeError(f"{self.name} load failed: {last_err}")

    @staticmethod
    def _patch_llama_flash_attn() -> None:
        """Shim transformers API drift for DeepSeek remote modeling code."""
        try:
            import transformers.utils.import_utils as iu

            if not hasattr(iu, "is_torch_fx_available"):
                iu.is_torch_fx_available = lambda: False  # type: ignore[attr-defined]
                print("  deepseek: stubbed is_torch_fx_available → False", flush=True)
            # other symbols remote code sometimes imports
            for name, default in (
                ("is_torch_fx_proxy", lambda x: False),
                ("is_flash_attn_2_available", lambda: False),
                ("is_flash_attn_greater_or_equal_2_10", lambda: False),
            ):
                if not hasattr(iu, name):
                    setattr(iu, name, default)
        except Exception:
            pass
        try:
            import transformers.models.llama.modeling_llama as llama_mod
        except Exception:
            return
        if hasattr(llama_mod, "LlamaFlashAttention2"):
            return
        standin = getattr(llama_mod, "LlamaSdpaAttention", None) or getattr(
            llama_mod, "LlamaAttention", None
        )
        if standin is not None:
            llama_mod.LlamaFlashAttention2 = standin
            print(
                "  deepseek: stubbed LlamaFlashAttention2 → "
                f"{standin.__name__} (transformers API drift)",
                flush=True,
            )

    def run(self, image_path: Path) -> str:
        prompt = self.prompt
        out_dir = OUT_DIR / f"_{self.name}_tmp" / image_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        # DeepSeek remote infer() only *returns* text when eval_mode=True;
        # with the default False it runs generation but returns None.
        infer_kwargs = dict(
            prompt=prompt,
            image_file=str(image_path),
            output_path=str(out_dir),
            base_size=self.base_size,
            image_size=self.image_size,
            crop_mode=self.crop_mode,
            save_results=True,
            test_compress=False,
            eval_mode=True,
        )
        try:
            res = self.model.infer(self.tokenizer, **infer_kwargs)
        except TypeError:
            # older / Unlimited forks may reject test_compress / eval_mode
            infer_kwargs.pop("test_compress", None)
            try:
                res = self.model.infer(self.tokenizer, **infer_kwargs)
            except TypeError:
                infer_kwargs.pop("eval_mode", None)
                res = self.model.infer(self.tokenizer, **infer_kwargs)
        text = ""
        if isinstance(res, str):
            text = res.strip()
        elif isinstance(res, (list, tuple)) and res:
            text = str(res[0]).strip()
        elif res is not None:
            text = str(res).strip()
        if not text:
            mmd = out_dir / "result.mmd"
            if mmd.exists():
                text = mmd.read_text(encoding="utf-8", errors="replace").strip()
        # strip end-of-sentence marker if present
        stop = "<｜end▁of▁sentence｜>"
        if text.endswith(stop):
            text = text[: -len(stop)].strip()
        return text

    def close(self) -> None:
        del self.model, self.tokenizer
        unload_cuda()


class UnlimitedRunner(DeepseekRunner):
    """baidu/Unlimited-OCR — same AutoModel.infer surface as DeepSeek-OCR."""

    name = "unlimited"
    candidates = ("baidu/Unlimited-OCR",)
    prompt = "<image>\nFree OCR. "
    image_size = 640
    # Model card also documents document-parsing prompt; Free OCR matches title metric.


class GlmRunner:
    """zai-org/GLM-OCR via AutoModelForImageTextToText.

    Official prompts are limited; use "Text Recognition:" (not free-form OCR_PROMPT).
    """

    name = "glm"
    hf_id = MODEL_IDS["glm"]
    prompt = "Text Recognition:"

    def __init__(self, device: str):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.device = device
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        kwargs: dict = {"torch_dtype": dtype}
        if device == "cuda":
            kwargs["device_map"] = "auto"
        # Card prefers torch_dtype="auto"; fall back to explicit dtype
        try:
            self.model = AutoModelForImageTextToText.from_pretrained(
                self.hf_id, torch_dtype="auto", device_map="auto" if device == "cuda" else None
            )
        except Exception:
            self.model = AutoModelForImageTextToText.from_pretrained(self.hf_id, **kwargs)
        if device != "cuda" and not hasattr(self.model, "hf_device_map"):
            self.model = self.model.to(device)
        self.model.eval()
        self.processor = AutoProcessor.from_pretrained(self.hf_id)
        print(f"  glm loaded: {self.hf_id}", flush=True)

    def run(self, image_path: Path) -> str:
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        # Prefer official url-style content; fall back to PIL image key
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "url": str(image_path)},
                    {"type": "text", "text": self.prompt},
                ],
            }
        ]
        try:
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
        except Exception:
            messages_pil = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": self.prompt},
                    ],
                }
            ]
            try:
                inputs = self.processor.apply_chat_template(
                    messages_pil,
                    tokenize=True,
                    add_generation_prompt=True,
                    return_dict=True,
                    return_tensors="pt",
                )
            except TypeError:
                text = self.processor.apply_chat_template(
                    messages_pil, add_generation_prompt=True, tokenize=False
                )
                inputs = self.processor(
                    text=[text], images=[image], return_tensors="pt"
                )

        if hasattr(inputs, "pop"):
            inputs.pop("token_type_ids", None)
        elif isinstance(inputs, dict):
            inputs.pop("token_type_ids", None)

        inputs = _move_inputs_to_model(self.model, inputs, self.device)

        import torch

        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=1024, do_sample=False)
        in_len = inputs["input_ids"].shape[1]
        # Card uses skip_special_tokens=False; for title_overlap plain text is better
        text = self.processor.decode(
            out[0][in_len:], skip_special_tokens=True
        )
        return (text or "").strip()

    def close(self) -> None:
        del self.model, self.processor
        unload_cuda()


class ChatVlRunner:
    """Generic AutoModelForImageTextToText + chat template (qianfan).

    Do not use for Qwen2-VL (CausalLM fallback breaks) or PaddleOCR-VL
    (ACT2FN / rope KeyError 'default') — those have dedicated runners.
    """

    def __init__(self, name: str, hf_id: str, device: str, prompt: str):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.name = name
        self.hf_id = hf_id
        self.device = device
        self.prompt = prompt
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        kwargs: dict = {"torch_dtype": dtype, "trust_remote_code": True}
        if device == "cuda":
            kwargs["device_map"] = "auto"
        try:
            self.model = AutoModelForImageTextToText.from_pretrained(hf_id, **kwargs)
        except Exception:
            # older HF APIs / CausalLM checkpoints (qianfan-style only)
            from transformers import AutoModelForCausalLM

            self.model = AutoModelForCausalLM.from_pretrained(hf_id, **kwargs)
        if device != "cuda" and not hasattr(self.model, "hf_device_map"):
            self.model = self.model.to(device)
        self.model.eval()
        self.processor = AutoProcessor.from_pretrained(hf_id, trust_remote_code=True)

    def run(self, image_path: Path) -> str:
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": self.prompt},
                ],
            }
        ]
        try:
            inputs = self.processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            )
        except TypeError:
            text = self.processor.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False
            )
            inputs = self.processor(text=[text], images=[image], return_tensors="pt")

        model_device = getattr(self.model, "device", None)
        if model_device is None:
            try:
                model_device = next(self.model.parameters()).device
            except StopIteration:
                model_device = self.device
        if hasattr(inputs, "to"):
            inputs = inputs.to(model_device)
        else:
            inputs = {
                k: v.to(model_device) if hasattr(v, "to") else v for k, v in inputs.items()
            }

        import torch

        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=1024, do_sample=False)
        in_len = inputs["input_ids"].shape[1]
        text = self.processor.batch_decode(out[:, in_len:], skip_special_tokens=True)[0]
        return (text or "").strip()

    def close(self) -> None:
        del self.model, self.processor
        unload_cuda()


def _patch_act_default(cfg) -> None:
    """PaddleOCR-VL configs sometimes ship hidden_act='default' (not in ACT2FN)."""
    if cfg is None:
        return
    for key in ("hidden_act", "hidden_activation", "activation_function"):
        if getattr(cfg, key, None) == "default":
            setattr(cfg, key, "silu")
    # nested text / vision configs
    for nested in ("text_config", "vision_config", "llm_config"):
        sub = getattr(cfg, nested, None)
        if sub is not None and sub is not cfg:
            _patch_act_default(sub)
    # rope_type 'default' → KeyError in some remote-code ROPE_INIT_FUNCTIONS maps
    if getattr(cfg, "rope_type", None) == "default":
        try:
            cfg.rope_type = "default"  # keep; see _patch_rope_default()
        except Exception:
            pass
    rope = getattr(cfg, "rope_scaling", None)
    if isinstance(rope, dict):
        # leave rope_type as-is; ROPE_INIT_FUNCTIONS is patched separately
        pass


def _patch_rope_default() -> None:
    """Register rope_type='default' so Paddle remote code does not KeyError."""
    try:
        from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
    except Exception:
        try:
            from transformers.modeling_utils import ROPE_INIT_FUNCTIONS  # type: ignore
        except Exception:
            return
    if "default" not in ROPE_INIT_FUNCTIONS:
        for alias in ("llama", "linear"):
            if alias in ROPE_INIT_FUNCTIONS:
                ROPE_INIT_FUNCTIONS["default"] = ROPE_INIT_FUNCTIONS[alias]
                print(f"  paddle: ROPE_INIT_FUNCTIONS['default'] ← {alias}", flush=True)
                break
        else:
            if ROPE_INIT_FUNCTIONS:
                first = next(iter(ROPE_INIT_FUNCTIONS.values()))
                ROPE_INIT_FUNCTIONS["default"] = first
                print("  paddle: ROPE_INIT_FUNCTIONS['default'] ← first available", flush=True)
    # Also map ACT2FN['default'] if missing (older remote code / configs)
    try:
        from transformers.activations import ACT2FN

        if "default" not in ACT2FN:
            ACT2FN["default"] = ACT2FN.get("silu") or ACT2FN.get("gelu") or next(iter(ACT2FN.values()))
            print("  paddle: ACT2FN['default'] ← silu/gelu", flush=True)
    except Exception:
        pass


def _move_inputs_to_model(model, inputs, fallback_device: str):
    model_device = getattr(model, "device", None)
    if model_device is None:
        try:
            model_device = next(model.parameters()).device
        except StopIteration:
            model_device = fallback_device
    if hasattr(inputs, "to"):
        return inputs.to(model_device)
    return {k: v.to(model_device) if hasattr(v, "to") else v for k, v in inputs.items()}


class PaddleRunner:
    """PaddleOCR-VL with ACT2FN / rope patches.

    HF note: there is no separate `PaddlePaddle/PaddleOCR-VL-0.9B` repo — the 0.9B
    weights live at `PaddlePaddle/PaddleOCR-VL`. Fallbacks try 1.5 then 1.6.
    Official load path uses AutoModelForCausalLM + trust_remote_code (not CausalLM
    fallback after ImageTextToText). Prompt: 'OCR:'.
    """

    name = "paddle"
    candidates = (
        MODEL_IDS["paddle"],  # PaddlePaddle/PaddleOCR-VL (= 0.9B core)
        "PaddlePaddle/PaddleOCR-VL-1.5",
        "PaddlePaddle/PaddleOCR-VL-1.6",
    )
    prompt = "OCR:"

    def __init__(self, device: str):
        import torch
        from transformers import AutoConfig, AutoProcessor

        self.device = device
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        last_err: Exception | None = None
        self.model = None
        self.processor = None
        self.hf_id = self.candidates[0]
        _patch_rope_default()

        for mid in self.candidates:
            errors: list[str] = []
            try:
                config = AutoConfig.from_pretrained(mid, trust_remote_code=True)
                _patch_act_default(config)
                base_kwargs: dict = {
                    "torch_dtype": dtype,
                    "trust_remote_code": True,
                }
                # Prefer official HF README path: CausalLM + trust_remote_code
                loaders = []
                try:
                    from transformers import AutoModelForCausalLM

                    loaders.append(("AutoModelForCausalLM", AutoModelForCausalLM))
                except Exception as e:
                    errors.append(f"import CausalLM: {e}")
                try:
                    from transformers.models.paddleocr_vl.modeling_paddleocr_vl import (
                        PaddleOCRVLForConditionalGeneration,
                    )

                    loaders.append(
                        ("PaddleOCRVLForConditionalGeneration", PaddleOCRVLForConditionalGeneration)
                    )
                except Exception as e:
                    errors.append(f"import native paddleocr_vl: {e}")
                try:
                    from transformers import AutoModelForImageTextToText

                    loaders.append(
                        ("AutoModelForImageTextToText", AutoModelForImageTextToText)
                    )
                except Exception as e:
                    errors.append(f"import ImageTextToText: {e}")

                model = None
                for label, cls in loaders:
                    for with_cfg in (True, False):
                        kwargs = dict(base_kwargs)
                        if device == "cuda":
                            # remote CausalLM often prefers .to(device) over device_map
                            if label == "AutoModelForCausalLM":
                                pass
                            else:
                                kwargs["device_map"] = "auto"
                        if with_cfg:
                            kwargs["config"] = config
                        try:
                            model = cls.from_pretrained(mid, **kwargs)
                            print(f"  paddle loaded via {label} cfg={with_cfg}: {mid}", flush=True)
                            break
                        except Exception as e:
                            errors.append(f"{label} cfg={with_cfg}: {e}")
                            model = None
                    if model is not None:
                        break

                if model is None:
                    last_err = RuntimeError("; ".join(errors[-6:]) or "unknown")
                    print(f"  paddle try failed {mid}: {last_err}", flush=True)
                    unload_cuda()
                    continue

                if device == "cuda" and not hasattr(model, "hf_device_map"):
                    model = model.to(device)
                elif device != "cuda" and not hasattr(model, "hf_device_map"):
                    model = model.to(device)
                model.eval()
                processor = AutoProcessor.from_pretrained(mid, trust_remote_code=True)
                self.model = model
                self.processor = processor
                self.hf_id = mid
                break
            except Exception as e:
                last_err = e
                print(f"  paddle candidate error {mid}: {e}", flush=True)
                unload_cuda()

        if self.model is None:
            raise RuntimeError(
                f"PaddleOCR-VL load failed (tried {self.candidates}; "
                f"note: no HF id PaddleOCR-VL-0.9B — use PaddleOCR-VL): {last_err}"
            )

    def run(self, image_path: Path) -> str:
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": self.prompt},
                ],
            }
        ]
        try:
            inputs = self.processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            )
        except TypeError:
            text = self.processor.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False
            )
            inputs = self.processor(text=[text], images=[image], return_tensors="pt")

        inputs = _move_inputs_to_model(self.model, inputs, self.device)

        import torch

        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=1024, do_sample=False)
        in_len = inputs["input_ids"].shape[1]
        text = self.processor.batch_decode(out[:, in_len:], skip_special_tokens=True)[0]
        return (text or "").strip()

    def close(self) -> None:
        del self.model, self.processor
        unload_cuda()


class QwenRunner:
    """Qwen2-VL via Qwen2VLForConditionalGeneration (no CausalLM fallback).

    Keys: qwen (2B) and qwen7 (7B). On CUDA OOM for 7B, retry with bitsandbytes 4bit.
    """

    prompt = OCR_PROMPT

    def __init__(self, device: str, name: str = "qwen", hf_id: str | None = None):
        import torch
        from transformers import AutoProcessor

        self.name = name
        self.hf_id = hf_id or MODEL_IDS[name]
        self.device = device
        dtype = torch.bfloat16 if device == "cuda" else torch.float32

        # g4dn.xlarge (~16 GB): bf16 7B loads via CPU offload but OOMs on large
        # homolog posters during generate. Prefer 4bit unless QWEN7_LOAD=bf16.
        import os

        force_4bit = False
        if name == "qwen7" and device == "cuda":
            prefer = (os.environ.get("QWEN7_LOAD") or "4bit").strip().lower()
            force_4bit = prefer in ("4bit", "bnb", "int4")

        model = None
        load_mode = "4bit" if force_4bit else "bf16"
        try:
            model = self._load_model(
                self.hf_id, device, dtype, load_in_4bit=force_4bit
            )
        except Exception as e:
            err = str(e).lower()
            oomish = (
                device == "cuda"
                and name == "qwen7"
                and not force_4bit
                and ("out of memory" in err or "cuda" in err or "oom" in err)
            )
            if not oomish:
                raise
            print(
                f"  {name}: bf16 load failed ({e}); retrying bitsandbytes 4bit…",
                flush=True,
            )
            unload_cuda()
            model = self._load_model(self.hf_id, device, dtype, load_in_4bit=True)
            load_mode = "4bit"

        if device != "cuda" and not hasattr(model, "hf_device_map"):
            model = model.to(device)
        self.model = model.eval()
        self.processor = AutoProcessor.from_pretrained(self.hf_id)
        print(f"  {name} loaded: {self.hf_id} mode={load_mode}", flush=True)

    @staticmethod
    def _load_model(hf_id: str, device: str, dtype, load_in_4bit: bool = False):
        kwargs: dict = {}
        if load_in_4bit:
            try:
                from transformers import BitsAndBytesConfig
            except Exception as e:
                raise RuntimeError(
                    f"bitsandbytes/BitsAndBytesConfig required for 4bit: {e}"
                ) from e
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=dtype,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
            kwargs["device_map"] = "auto"
        else:
            kwargs["torch_dtype"] = dtype
            if device == "cuda":
                kwargs["device_map"] = "auto"

        try:
            from transformers import Qwen2VLForConditionalGeneration

            return Qwen2VLForConditionalGeneration.from_pretrained(hf_id, **kwargs)
        except Exception:
            from transformers import AutoModelForImageTextToText

            return AutoModelForImageTextToText.from_pretrained(hf_id, **kwargs)

    def run(self, image_path: Path) -> str:
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": str(image_path)},
                    {"type": "text", "text": self.prompt},
                ],
            }
        ]

        # Prefer qwen_vl_utils.process_vision_info when available
        try:
            from qwen_vl_utils import process_vision_info

            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            image_inputs, video_inputs = process_vision_info(messages)
            inputs = self.processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            )
        except Exception:
            # Fallback: processor(text=, images=) chat-template pattern
            messages_pil = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": self.prompt},
                    ],
                }
            ]
            text = self.processor.apply_chat_template(
                messages_pil, tokenize=False, add_generation_prompt=True
            )
            inputs = self.processor(
                text=[text], images=[image], padding=True, return_tensors="pt"
            )

        inputs = _move_inputs_to_model(self.model, inputs, self.device)

        import torch

        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=1024, do_sample=False)
        in_len = inputs["input_ids"].shape[1]
        text = self.processor.batch_decode(
            out[:, in_len:], skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]
        return (text or "").strip()

    def close(self) -> None:
        del self.model, self.processor
        unload_cuda()


class KimiRunner:
    """Moonshot Kimi-VL-A3B via AutoModelForCausalLM + trust_remote_code.

    16B total MoE / ~2.8B activated. On 24GB (g5.2xlarge A10G) default to 4bit
    via bitsandbytes; set KIMI_LOAD=bf16 to try full bf16 first (may OOM).
    If Instruct fails to load, set KIMI_HF_ID=moonshotai/Kimi-VL-A3B-Thinking.
    """

    prompt = OCR_PROMPT
    name = "kimi"

    def __init__(self, device: str, hf_id: str | None = None):
        import os

        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        self.device = device
        self.hf_id = (
            hf_id
            or (os.environ.get("KIMI_HF_ID") or "").strip()
            or MODEL_IDS["kimi"]
        )
        prefer = (os.environ.get("KIMI_LOAD") or "4bit").strip().lower()
        force_4bit = prefer in ("4bit", "bnb", "int4")
        force_8bit = prefer in ("8bit", "int8")

        model = None
        load_mode = "4bit" if force_4bit else ("8bit" if force_8bit else "bf16")
        try:
            model = self._load_model(
                self.hf_id,
                device,
                load_in_4bit=force_4bit,
                load_in_8bit=force_8bit,
            )
        except Exception as e:
            err = str(e).lower()
            oomish = device == "cuda" and not force_4bit and (
                "out of memory" in err or "cuda" in err or "oom" in err
            )
            if not oomish:
                raise
            print(
                f"  kimi: {load_mode} load failed ({e}); retrying bitsandbytes 4bit…",
                flush=True,
            )
            unload_cuda()
            model = self._load_model(
                self.hf_id, device, load_in_4bit=True, load_in_8bit=False
            )
            load_mode = "4bit"

        self.model = model.eval()
        self.processor = AutoProcessor.from_pretrained(
            self.hf_id, trust_remote_code=True
        )
        print(f"  kimi loaded: {self.hf_id} mode={load_mode}", flush=True)

    @staticmethod
    def _load_model(
        hf_id: str,
        device: str,
        load_in_4bit: bool = False,
        load_in_8bit: bool = False,
    ):
        import torch
        from transformers import AutoModelForCausalLM

        kwargs: dict = {"trust_remote_code": True}
        if load_in_4bit or load_in_8bit:
            try:
                from transformers import BitsAndBytesConfig
            except Exception as e:
                raise RuntimeError(
                    f"bitsandbytes/BitsAndBytesConfig required for quantized load: {e}"
                ) from e
            if load_in_4bit:
                kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                )
            else:
                kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_8bit=True,
                )
            kwargs["device_map"] = "auto"
        else:
            kwargs["torch_dtype"] = "auto"
            if device == "cuda":
                kwargs["device_map"] = "auto"

        return AutoModelForCausalLM.from_pretrained(hf_id, **kwargs)

    def run(self, image_path: Path) -> str:
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": str(image_path)},
                    {"type": "text", "text": self.prompt},
                ],
            }
        ]
        text = self.processor.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt"
        )
        inputs = self.processor(
            images=image,
            text=text,
            return_tensors="pt",
            padding=True,
            truncation=True,
        )
        inputs = _move_inputs_to_model(self.model, inputs, self.device)

        import torch

        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs, max_new_tokens=1024, do_sample=False
            )
        trimmed = [
            out_ids[len(in_ids) :]
            for in_ids, out_ids in zip(inputs["input_ids"], generated_ids)
        ]
        response = self.processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
        return (response or "").strip()

    def close(self) -> None:
        del self.model, self.processor
        unload_cuda()


def build_runner(key: str, device: str):
    if key == "got":
        return GotRunner(device)
    if key == "deepseek":
        return DeepseekRunner(device)
    if key == "deepseek2":
        return DeepseekRunner(
            device,
            name="deepseek2",
            candidates=("deepseek-ai/DeepSeek-OCR-2",),
            image_size=768,
        )
    if key == "unlimited":
        return UnlimitedRunner(device)
    if key == "glm":
        return GlmRunner(device)
    if key == "paddle":
        return PaddleRunner(device)
    if key == "qianfan":
        return ChatVlRunner(
            "qianfan",
            MODEL_IDS["qianfan"],
            device,
            "Extract all visible text from this movie poster as plain text.",
        )
    if key == "qwen":
        return QwenRunner(device, name="qwen")
    if key == "qwen7":
        return QwenRunner(device, name="qwen7")
    if key == "kimi":
        return KimiRunner(device)
    raise ValueError(f"unknown model key: {key}")


def run_model_on_sample(
    key: str,
    sample: pd.DataFrame,
    device: str,
    rows: list[dict],
    result_model: str | None = None,
) -> None:
    tag = result_model or key
    print(
        f"\n=== model={key} result_model={tag} device={device} "
        f"n={len(sample)} posters={POSTERS} ===",
        flush=True,
    )
    try:
        runner = build_runner(key, device)
    except Exception as e:
        msg = f"load_error: {e}"
        print(msg, flush=True)
        traceback.print_exc()
        for _, r in sample.iterrows():
            append_result(
                rows,
                {
                    "id": int(r["id"]),
                    "title": r.get("title", ""),
                    "year": r.get("year", ""),
                    "model": tag,
                    "text": "",
                    "chars": 0,
                    "title_overlap_score": 0.0,
                    "latency_s": 0.0,
                    "status": msg[:500],
                },
            )
        unload_cuda()
        return

    try:
        for _, r in sample.iterrows():
            pid = int(r["id"])
            title = str(r.get("title") or "")
            year = r.get("year", "")
            img = POSTERS / f"{pid}.jpg"
            t0 = time.perf_counter()
            status = "ok"
            text = ""
            try:
                if not img.exists():
                    raise FileNotFoundError(f"missing {img}")
                text = runner.run(img) or ""
            except Exception as e:
                status = f"error: {e}"[:500]
                print(f"  id={pid} FAIL {status}", flush=True)
                traceback.print_exc()
                # OOM: try to recover GPU for remaining images
                if "out of memory" in str(e).lower() or "cuda" in str(e).lower():
                    unload_cuda()
            lat = round(time.perf_counter() - t0, 3)
            score = title_overlap_score(text, title) if status == "ok" else 0.0
            append_result(
                rows,
                {
                    "id": pid,
                    "title": title,
                    "year": year,
                    "model": tag,
                    "text": text.replace("\n", "\\n") if status == "ok" else "",
                    "chars": len(text) if status == "ok" else 0,
                    "title_overlap_score": score,
                    "latency_s": lat,
                    "status": status,
                },
            )
            # also keep raw multiline in txt (append_result already wrote if ok)
            if status == "ok":
                (OUT_DIR / tag / f"{pid}.txt").write_text(text, encoding="utf-8")
            print(
                f"  id={pid} status={status[:40]} chars={len(text)} "
                f"overlap={score} {lat}s",
                flush=True,
            )
    finally:
        try:
            runner.close()
        except Exception:
            unload_cuda()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=20, help="sample size (default 20)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ids-file", default="", help="optional id list (one per line or csv)")
    ap.add_argument(
        "--models",
        default="got,deepseek,paddle,qianfan,qwen",
        help="comma-separated: got,deepseek,deepseek2,unlimited,glm,paddle,"
        "qianfan,qwen,qwen7,kimi",
    )
    ap.add_argument(
        "--dry-sample",
        action="store_true",
        help="only write sample_ids.txt (+ posters subset meta), no inference",
    )
    ap.add_argument("--device", default="", help="force cuda|mps|cpu")
    ap.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="output dir (default: data/qa/ocr_pilot; use ocr_pilot_v2 for Medium eval)",
    )
    ap.add_argument(
        "--posters-dir",
        default="",
        help="override posters directory (default: data/posters)",
    )
    ap.add_argument(
        "--result-model",
        default="",
        help="write this name in results.csv / txt dirs while still loading --models "
        "(requires exactly one model key; e.g. --models qwen --result-model qwen-homolog)",
    )
    ap.add_argument(
        "--append-results",
        action="store_true",
        default=True,
        help="merge into existing results.csv (replace only models being re-run; default)",
    )
    ap.add_argument(
        "--no-append-results",
        action="store_false",
        dest="append_results",
        help="ignore prior results.csv and write only models in --models",
    )
    args = ap.parse_args()
    configure_out_dir(args.out_dir)
    if args.posters_dir:
        configure_posters_dir(args.posters_dir)

    keys = [k.strip().lower() for k in args.models.split(",") if k.strip()]
    for k in keys:
        if k not in MODEL_IDS:
            raise SystemExit(f"unknown model '{k}'; choose from {list(MODEL_IDS)}")

    result_alias = (args.result_model or "").strip()
    if result_alias and len(keys) != 1:
        raise SystemExit("--result-model requires exactly one entry in --models")
    result_tags = {keys[0]: result_alias} if result_alias else {}
    write_keys = [result_tags.get(k, k) for k in keys]

    sample = load_sample(args.n, args.seed, args.ids_file or None)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_IDS.write_text(
        "\n".join(str(int(x)) for x in sample["id"].tolist()) + "\n",
        encoding="utf-8",
    )
    meta = sample[["id", "title", "year"]].copy()
    if "text_area" in sample.columns:
        meta["text_area"] = sample["text_area"]
    meta.to_csv(OUT_DIR / "sample_meta.csv", index=False)
    print(f"sample n={len(sample)} → {SAMPLE_IDS}", flush=True)
    print(f"posters_dir={POSTERS}", flush=True)
    if result_alias:
        print(f"result_model alias: {keys[0]} → {result_alias}", flush=True)
    print(sample[["id", "title", "year"]].to_string(index=False), flush=True)

    if args.dry_sample:
        print("dry-sample only — exiting", flush=True)
        return 0

    device = args.device or pick_device()
    print(f"device={device}", flush=True)

    # Merge mode: keep prior rows for models not being re-run (e.g. retry deepseek
    # while preserving got+qianfan).
    rows: list[dict] = []
    if args.append_results and RESULTS_CSV.exists():
        with RESULTS_CSV.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                if r.get("model") not in write_keys:
                    rows.append(r)
        print(
            f"append-results: kept {len(rows)} rows for models outside {write_keys}",
            flush=True,
        )

    for key in keys:
        tag = result_tags.get(key, key)
        # drop previous rows for this model tag (re-run)
        rows = [r for r in rows if r.get("model") != tag]
        run_model_on_sample(key, sample, device, rows, result_model=tag)

    write_results(rows)
    print(f"\nLISTO → {RESULTS_CSV} ({len(rows)} rows)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
