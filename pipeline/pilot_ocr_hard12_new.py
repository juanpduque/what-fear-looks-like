#!/usr/bin/env python3
"""Hard12 runner: GLM-OCR + Unlimited-OCR + DeepSeek-OCR-2.

Thin wrapper around pilot_ocr_models.py with hard-set defaults
(same 12 ids as ocr_qwen_hard / ocr_kimi_hard).

Local (needs GPU + staged posters):
  python3 pilot_ocr_hard12_new.py --dry-sample
  python3 pilot_ocr_hard12_new.py
  python3 pilot_ocr_hard12_new.py --models glm
  python3 pilot_ocr_hard12_new.py --models unlimited,deepseek2

AWS:
  bash aws/stage_ocr_hard12_new.sh
  MODELS=glm,unlimited,deepseek2 bash aws/launch_ocr_hard12_new.sh
  bash aws/pull_ocr_hard12_new.sh

Result model tags written to results.csv:
  glm       → glm-ocr-hard
  unlimited → unlimited-ocr-hard
  deepseek2 → deepseek-ocr2-hard
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PIPE = Path(__file__).resolve().parent
HARD_IDS = PIPE / "data" / "qa" / "ocr_qwen_hard" / "sample_ids.txt"
OUT_DIR = PIPE / "data" / "qa" / "ocr_hard12_new"
DEFAULT_POSTERS = PIPE / "data" / "qa" / "_ocr_hard12_new_stage" / "posters"
FALLBACK_POSTERS = PIPE / "data" / "qa" / "_ocr_qwen_hard_stage" / "posters"
FALLBACK_POSTERS2 = PIPE / "data" / "posters"

RESULT_TAGS = {
    "glm": "glm-ocr-hard",
    "unlimited": "unlimited-ocr-hard",
    "deepseek2": "deepseek-ocr2-hard",
}
DEFAULT_MODELS = "glm,unlimited,deepseek2"


def resolve_posters_dir(explicit: str) -> Path:
    if explicit:
        return Path(explicit)
    for cand in (DEFAULT_POSTERS, FALLBACK_POSTERS, FALLBACK_POSTERS2):
        if cand.is_dir() and any(cand.glob("*.jpg")):
            return cand
    return DEFAULT_POSTERS


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=DEFAULT_MODELS, help=f"default: {DEFAULT_MODELS}")
    ap.add_argument("--ids-file", default=str(HARD_IDS))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--posters-dir", default="", help="override posters dir")
    ap.add_argument("--device", default="")
    ap.add_argument("--dry-sample", action="store_true")
    ap.add_argument(
        "--no-result-alias",
        action="store_true",
        help="write raw model keys (glm/unlimited/deepseek2) instead of *-hard tags",
    )
    args = ap.parse_args()

    ids_file = Path(args.ids_file)
    if not ids_file.is_file():
        raise SystemExit(f"missing ids file: {ids_file}")

    posters = resolve_posters_dir(args.posters_dir)
    keys = [k.strip().lower() for k in args.models.split(",") if k.strip()]
    unknown = [k for k in keys if k not in RESULT_TAGS]
    if unknown:
        raise SystemExit(f"unknown hard12 models {unknown}; choose from {list(RESULT_TAGS)}")

    # Sequential one-model runs so each gets the *-hard result tag (pilot requires
    # --result-model with exactly one --models key).
    rc_all = 0
    for i, key in enumerate(keys):
        cmd = [
            sys.executable,
            "-u",
            str(PIPE / "pilot_ocr_models.py"),
            "--ids-file",
            str(ids_file),
            "--out-dir",
            str(args.out_dir),
            "--posters-dir",
            str(posters),
            "--models",
            key,
            "--append-results",
            "--n",
            "12",
        ]
        if not args.no_result_alias:
            cmd.extend(["--result-model", RESULT_TAGS[key]])
        if args.device:
            cmd.extend(["--device", args.device])
        if args.dry_sample:
            cmd.append("--dry-sample")
            # dry-sample only needs one pass
            print(" ".join(cmd), flush=True)
            return subprocess.call(cmd, cwd=str(PIPE))

        print(f"\n=== hard12 [{i + 1}/{len(keys)}] {' '.join(cmd)} ===", flush=True)
        rc = subprocess.call(cmd, cwd=str(PIPE))
        if rc != 0:
            rc_all = rc
            print(f"WARN: model={key} exit={rc} — continuing", flush=True)

    return rc_all


if __name__ == "__main__":
    sys.exit(main())
